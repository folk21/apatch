"""Load and validate the user-provided handoff and local configuration."""

import configparser
import json
import re
import shlex
from dataclasses import dataclass, replace
from pathlib import Path


BRANCH_PATTERN = re.compile(r"^feature/[A-Za-z0-9][A-Za-z0-9._/-]*$")
BASENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.zip$")
SHA_PATTERN = re.compile(r"^[a-f0-9]{40}$")
DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class Abort(RuntimeError):
    """A precondition failed; no further workflow step is safe."""


@dataclass(frozen=True)
class Config:
    downloads: Path
    state_path: Path
    log_directory: Path
    applied_patches_path: Path
    remote: str
    base: str
    checks: tuple[tuple[str, ...], ...]
    require_approval: bool
    require_checks: bool
    merge_method: str
    max_bytes: int
    require_patch_feature_branch: bool = False


@dataclass(frozen=True)
class Handoff:
    repository: str
    branch: str
    patch: str
    message: str
    base_commit: str | None
    patch_sha256: str | None
    delete_paths: tuple[str, ...]

    @property
    def subject(self):
        return self.message.splitlines()[0]


def load_config(script_dir: Path) -> Config:
    parser = configparser.ConfigParser(interpolation=None)
    config_path = script_dir / "apatch.conf"
    try:
        loaded = parser.read(config_path, encoding="utf-8")
    except configparser.Error as exc:
        raise Abort(f"Invalid global configuration: {exc}") from exc
    if loaded != [str(config_path)]:
        raise Abort(f"Missing configuration: {config_path}")
    section = parser["apatch"]
    state = Path(section.get("state_file", "signalharvester_apply_patch.state.json")).expanduser()
    if not state.is_absolute():
        state = script_dir / state
    log_directory = validate_log_subdirectory(section.get("log_directory", "logs"))
    applied_patches = Path(section.get("applied_patches_file", "signalharvester_applied_patches.txt")).expanduser()
    if not applied_patches.is_absolute():
        applied_patches = script_dir / applied_patches
    remote = section.get("remote", "origin")
    base = section.get("base_branch", "main")
    method = section.get("merge_method", "merge")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", remote):
        raise Abort("Invalid remote")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", base):
        raise Abort("Invalid base branch")
    if method not in {"merge", "squash", "rebase"}:
        raise Abort("merge_method must be merge, squash or rebase")
    return Config(
        downloads=Path(section.get("downloads_dir", "~/Downloads")).expanduser().resolve(),
        state_path=state.resolve(),
        log_directory=log_directory,
        applied_patches_path=applied_patches.parent.resolve() / applied_patches.name,
        remote=remote,
        base=base,
        checks=(),
        require_approval=section.getboolean("require_review_approval", True),
        require_checks=section.getboolean("require_required_checks", True),
        merge_method=method,
        max_bytes=section.getint("max_uncompressed_patch_bytes", 52428800),
        require_patch_feature_branch=section.getboolean("require_patch_feature_branch", False),
    )


def validate_log_subdirectory(value: str) -> Path:
    """Require a relative log directory contained within the project .apatch directory."""
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise Abort("log_directory must be a relative path inside the project .apatch directory")
    directory = Path(value)
    if directory.is_absolute():
        raise Abort("log_directory must be a relative path inside the project .apatch directory")
    return directory


def load_project_config(root: Path, global_config: Config) -> Config:
    config_dir = root / ".apatch"
    config_path = config_dir / "config.yaml"
    if config_dir.is_symlink() or config_path.is_symlink():
        raise Abort(f"Project config must not be a symlink: {config_path}")
    if not config_path.is_file():
        raise Abort(f"Missing project checks config: {config_path}")
    try:
        if config_path.stat().st_size > 65536:
            raise Abort("Project checks config exceeds 64 KiB")
        import yaml
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except ImportError as exc:
        raise Abort("PyYAML is required; install apatch/requirements.txt") from exc
    except (OSError, UnicodeError) as exc:
        raise Abort(f"Cannot read project checks config: {exc}") from exc
    except yaml.YAMLError as exc:
        raise Abort(f"Invalid project checks YAML: {exc}") from exc

    required = {"schema_version", "checks"}
    allowed = required | {"log_directory"}
    if not isinstance(data, dict) or not required <= set(data) or set(data) - allowed:
        raise Abort("Project config must contain schema_version and checks, with optional log_directory")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise Abort("Unsupported project checks schema_version")
    commands = data["checks"]
    if not isinstance(commands, list) or not commands:
        raise Abort("Project checks must be a non-empty list")
    parsed = []
    for index, command in enumerate(commands, start=1):
        if isinstance(command, str):
            try:
                argv = shlex.split(command)
            except ValueError as exc:
                raise Abort(f"Invalid quoting in project check {index}") from exc
        elif isinstance(command, list):
            argv = command
        else:
            raise Abort(f"Project check {index} must be a command string or argv list")
        if not argv or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
            raise Abort(f"Project check {index} contains invalid arguments")
        parsed.append(tuple(argv))
    subdirectory = validate_log_subdirectory(data.get("log_directory", str(global_config.log_directory)))
    location = config_dir / subdirectory
    for segment in (config_dir, *[config_dir.joinpath(*subdirectory.parts[:i]) for i in range(1, len(subdirectory.parts) + 1)]):
        if segment.is_symlink():
            raise Abort(f"Log directory must not contain symlinks: {segment}")
    return replace(global_config, checks=tuple(parsed), log_directory=location)


def safe_relative(path: str) -> str:
    if (not isinstance(path, str) or not path or "\\" in path or "\x00" in path
            or path.startswith("/") or any(p in {"", ".", ".."} for p in path.split("/"))
            or any(p == ".git" for p in path.split("/"))):
        raise Abort(f"Unsafe path: {path!r}")
    return path


def load_handoff(path: Path) -> Handoff:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Abort(f"Cannot read handoff JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise Abort("Unsupported handoff schema_version")
    expected = {"schema_version", "repository", "feature_branch", "patch_file", "commit_message",
                "base_commit", "patch_sha256", "delete_paths"}
    if set(payload) - expected:
        raise Abort(f"Unknown handoff keys: {sorted(set(payload) - expected)}")
    repo, branch = payload.get("repository"), payload.get("feature_branch")
    patch, msg = payload.get("patch_file"), payload.get("commit_message")
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", repo):
        raise Abort("Invalid repository")
    if not isinstance(branch, str) or not BRANCH_PATTERN.fullmatch(branch) or ".." in branch or branch.endswith("/"):
        raise Abort("Invalid feature_branch")
    if not isinstance(patch, str) or not BASENAME_PATTERN.fullmatch(patch):
        raise Abort("patch_file must be an ASCII-safe ZIP basename, without a directory")
    if not isinstance(msg, str) or not msg.strip() or len(msg) > 8192:
        raise Abort("commit_message is missing or too long")
    if not msg.splitlines()[0].strip() or "\x00" in msg:
        raise Abort("Invalid commit_message")
    base = payload.get("base_commit")
    digest = payload.get("patch_sha256")
    if base is not None and (not isinstance(base, str) or not SHA_PATTERN.fullmatch(base)):
        raise Abort("base_commit must be a full lowercase Git SHA")
    if digest is not None and (not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest)):
        raise Abort("patch_sha256 must be a lowercase SHA-256")
    paths = payload.get("delete_paths", [])
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise Abort("delete_paths must be a list of repository-relative paths")
    return Handoff(repo, branch, patch, msg.rstrip() + "\n", base, digest,
                   tuple(safe_relative(p) for p in paths))
