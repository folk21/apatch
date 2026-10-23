"""Keep project-local runtime artifacts out of Git without editing tracked files."""

import logging
from pathlib import Path

from .gitutil import output, run
from .model import Abort


LOGGER = logging.getLogger("apatch.local_ignore")


def ensure_runtime_ignored(root: Path, log_directory: Path, log_filename: str,
                           state_path: Path, history_path: Path) -> None:
    """Ignore project-local logs, state, history, and their locks in this Git worktree."""
    lock_path = state_path.with_name(state_path.name + ".lock")
    history_lock_path = history_path.with_name(history_path.name + ".lock")
    relative_log_dir = log_directory.relative_to(root).as_posix()
    patterns = {
        (log_directory / log_filename).relative_to(root).as_posix(): f"/{relative_log_dir}/",
        ".apatch/backups": "/.apatch/backups",
        state_path.relative_to(root).as_posix(): f"/{state_path.relative_to(root).as_posix()}",
        lock_path.relative_to(root).as_posix(): f"/{lock_path.relative_to(root).as_posix()}",
        history_path.relative_to(root).as_posix(): f"/{history_path.relative_to(root).as_posix()}",
        history_lock_path.relative_to(root).as_posix():
            f"/{history_lock_path.relative_to(root).as_posix()}",
    }

    missing = []
    for relative, pattern in patterns.items():
        tracked = run(["git", "ls-files", "--error-unmatch", "--", relative], root, check=False)
        if tracked.returncode == 0:
            raise Abort(f"Runtime artifact is tracked by Git: {relative}")
        if tracked.returncode != 1:
            raise Abort("Cannot verify whether a runtime artifact is tracked")
        check = ["git", "check-ignore", "--no-index", "--quiet", "--", relative]
        ignored = run(check, root, check=False)
        if ignored.returncode == 1:
            missing.append(pattern)
        elif ignored.returncode != 0:
            raise Abort("Cannot check Git ignore rules for a runtime artifact")
    if not missing:
        return

    path_value = output(["git", "rev-parse", "--git-path", "info/exclude"], root)
    exclude = Path(path_value)
    if not exclude.is_absolute():
        exclude = root / exclude
    if exclude.is_symlink() or (exclude.exists() and not exclude.is_file()):
        raise Abort(f"Unsafe local Git exclude file: {exclude}")
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a+b") as stream:
            stream.seek(0, 2)
            if stream.tell():
                stream.seek(-1, 2)
                last = stream.read(1)
                stream.seek(0, 2)
                if last != b"\n":
                    stream.write(b"\n")
            rules = "\n# apatch: local runtime artifacts\n" + "\n".join(missing) + "\n"
            stream.write(rules.encode("utf-8"))
    except OSError as exc:
        raise Abort(f"Cannot register local Git ignore rules for runtime artifacts: {exc}") from exc

    for relative in patterns:
        check = ["git", "check-ignore", "--no-index", "--quiet", "--", relative]
        if run(check, root, check=False).returncode != 0:
            raise Abort(f"Runtime artifact could not be excluded from Git: {relative}")
    LOGGER.info("local Git ignore rules registered for %s", ", ".join(missing))
