"""Keep project-local runtime logs out of Git without editing tracked files."""

import logging
from pathlib import Path

from .gitutil import output, run
from .model import Abort


LOGGER = logging.getLogger("apatch.local_ignore")


def ensure_log_ignored(root: Path, log_directory: Path, filename: str) -> None:
    """Add a narrowly scoped rule to this worktree's Git info/exclude if needed."""
    relative = log_directory.relative_to(root)
    log_file = (relative / filename).as_posix()
    tracked = run(["git", "ls-files", "--error-unmatch", "--", log_file], root, check=False)
    if tracked.returncode == 0:
        raise Abort(f"Project log file is tracked by Git: {log_file}")
    if tracked.returncode != 1:
        raise Abort("Cannot verify whether the project log file is tracked")

    check = ["git", "check-ignore", "--no-index", "--quiet", "--", log_file]
    result = run(check, root, check=False)
    if result.returncode == 0:
        return
    if result.returncode != 1:
        raise Abort("Cannot check Git ignore rules for the project log")

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
            stream.write(f"\n# apatch: local runtime logs\n/{relative.as_posix()}/\n".encode("utf-8"))
    except OSError as exc:
        raise Abort(f"Cannot register local Git ignore rule for project logs: {exc}") from exc

    if run(check, root, check=False).returncode != 0:
        raise Abort("Project logs could not be excluded from Git")
    LOGGER.info("local Git ignore rule registered for %s", relative)
