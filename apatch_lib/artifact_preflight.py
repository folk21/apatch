"""Producer-side source preparation and verification before creating a patch ZIP."""

from dataclasses import asdict, dataclass
from pathlib import Path

from .gitutil import (current_branch, head, output, run, worktree_change_details,
                      worktree_fingerprint, worktree_inventory)
from .model import Abort, load_config, load_project_config


@dataclass(frozen=True)
class PreflightResult:
    """Evidence for the exact worktree inspected before external ZIP packaging."""

    repository: str
    branch: str
    head: str
    changed_paths: tuple[str, ...]
    worktree_sha256: str
    prepared: bool
    format_commands_run: int
    check_commands_run: int

    def to_dict(self) -> dict:
        return {"status": "passed", **asdict(self)}


def _identity(root: Path) -> tuple[str, str]:
    branch = current_branch(root)
    if not branch:
        raise Abort("Artifact preflight requires a named Git branch (not detached HEAD)")
    return branch, head(root)


def _verify_identity(root: Path, expected: tuple[str, str], step: str) -> None:
    if _identity(root) != expected:
        raise Abort(f"{step} changed the Git branch or HEAD; source verification is invalid")


def _changed_paths(before: dict, after: dict) -> str:
    changes = worktree_change_details(before, after)
    names = [name for name, _ in changes]
    visible = ", ".join(repr(name) for name in names[:8])
    if len(names) > 8:
        visible += f", ... ({len(names)} paths total)"
    return visible or "unknown paths"


def _run_commands(root: Path, commands: tuple[tuple[str, ...], ...],
                  label: str, timeout: int, idle_timeout: int) -> None:
    for index, command in enumerate(commands, start=1):
        print(f"==> PREFLIGHT {label} {index}/{len(commands)}", flush=True)
        try:
            run(list(command), root, stream_output=True, timeout=timeout,
                idle_timeout=idle_timeout)
        except Abort as exc:
            raise Abort(f"{label} {index}/{len(commands)} failed: {exc}") from exc


def preflight(project: Path, installation: Path, *, prepare: bool = False) -> PreflightResult:
    """Verify source in its own Git checkout; never package or publish anything."""
    project = project.resolve()
    if not project.is_dir():
        raise Abort(f"Project directory does not exist: {project}")
    actual_root = Path(output(["git", "rev-parse", "--show-toplevel"], project)).resolve()
    if project != actual_root:
        raise Abort(f"Artifact preflight must run at the repository root: {actual_root}")
    config = load_project_config(project, load_config(installation))
    if not config.checks:
        raise Abort("Artifact preflight requires at least one canonical project check")
    expected_identity = _identity(project)
    original_index = run(["git", "ls-files", "--stage", "-z"], project, text=False).stdout
    if prepare:
        if not config.format_commands:
            raise Abort("--prepare requires project format_commands in .apatch/config.yaml")
        print("==> PREFLIGHT SOURCE PREPARATION (mutating)", flush=True)
        try:
            _run_commands(project, config.format_commands, "FORMAT",
                          config.check_timeout_seconds, config.check_idle_timeout_seconds)
        finally:
            _verify_identity(project, expected_identity, "Source preparation")
            updated_index = run(["git", "ls-files", "--stage", "-z"],
                                project, text=False).stdout
            if updated_index != original_index:
                raise Abort("Source preparation modified the Git index; inspect staged changes")

    print("==> PREFLIGHT READ-ONLY VERIFICATION", flush=True)
    before_checks = worktree_inventory(project)
    failure = None
    try:
        print("==> PREFLIGHT GIT WHITESPACE (unstaged)", flush=True)
        run(["git", "diff", "--check"], project)
        print("==> PREFLIGHT GIT WHITESPACE (staged)", flush=True)
        run(["git", "diff", "--cached", "--check"], project)
        _run_commands(project, config.checks, "CHECK", config.check_timeout_seconds,
                      config.check_idle_timeout_seconds)
    except Abort as exc:
        failure = exc

    after_checks = worktree_inventory(project)
    _verify_identity(project, expected_identity, "Read-only verification")
    if before_checks != after_checks:
        suffix = f"; original check error: {failure}" if failure else ""
        raise Abort("Read-only verification changed the source worktree or Git index: "
                    + _changed_paths(before_checks, after_checks) + suffix)
    if failure is not None:
        raise failure

    digest, changed_paths = worktree_fingerprint(project)
    _verify_identity(project, expected_identity, "Evidence capture")
    return PreflightResult(project.name, expected_identity[0], expected_identity[1],
                           tuple(sorted(changed_paths)), digest, prepare,
                           len(config.format_commands) if prepare else 0, len(config.checks))
