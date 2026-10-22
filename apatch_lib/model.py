"""Load and validate the user-provided handoff and local configuration."""

import configparser
import json
import re
from dataclasses import dataclass
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
    checks: tuple[str, ...]
    extra_checks: tuple[tuple[str, ...], ...]
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
    if parser.read(config_path, encoding="utf-8") != [str(config_path)]:
        raise Abort(f"Missing configuration: {config_path}")
    section = parser["apatch"]
    state = Path(section.get("state_file", "signalharvester_apply_patch.state.json")).expanduser()
    if not state.is_absolute():
        state = script_dir / state
    log_directory = Path(section.get("log_directory", "logs")).expanduser()
    if not log_directory.is_absolute():
        log_directory = script_dir / log_directory
    applied_patches = Path(section.get("applied_patches_file", "signalharvester_applied_patches.txt")).expanduser()
    if not applied_patches.is_absolute():
        applied_patches = script_dir / applied_patches
    checks = tuple(section.get("check_command", "./run_checks.sh").split())
    if not checks or checks[0] != "./run_checks.sh":
        raise Abort("check_command must start with ./run_checks.sh")
    remote = section.get("remote", "origin")
    base = section.get("base_branch", "main")
    method = section.get("merge_method", "merge")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", remote):
        raise Abort("Invalid remote")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", base):
        raise Abort("Invalid base branch")
    if method not in {"merge", "squash", "rebase"}:
        raise Abort("merge_method must be merge, squash or rebase")
    try:
        extra = json.loads(section.get("extra_check_commands_json", "[]"))
    except ValueError as exc:
        raise Abort("Invalid extra_check_commands_json") from exc
    if not isinstance(extra, list) or any(
        not isinstance(cmd, list) or not cmd or
        any(not isinstance(arg, str) or not arg for arg in cmd) for cmd in extra
    ):
        raise Abort("extra_check_commands_json must be an array of argv arrays")
    return Config(
        downloads=Path(section.get("downloads_dir", "~/Downloads")).expanduser().resolve(),
        state_path=state.resolve(),
        log_directory=log_directory.resolve(),
        applied_patches_path=applied_patches.parent.resolve() / applied_patches.name,
        remote=remote,
        base=base,
        checks=checks,
        extra_checks=tuple(tuple(command) for command in extra),
        require_approval=section.getboolean("require_review_approval", True),
        require_checks=section.getboolean("require_required_checks", True),
        merge_method=method,
        max_bytes=section.getint("max_uncompressed_patch_bytes", 52428800),
        require_patch_feature_branch=section.getboolean("require_patch_feature_branch", False),
    )


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
