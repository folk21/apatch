"""Stable advisory file locks shared by project-local persistence modules."""

import fcntl
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from ..model import Abort


@contextmanager
def exclusive_file_lock(path: Path, *, label: str):
    """Lock a regular inode without following symlinks or replacing the lock file."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"Unsafe {label} lock file: {path}")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "r+b") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise Abort(f"Unsafe {label} lock file: {path}")
            os.fchmod(handle.fileno(), 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise Abort(f"Cannot access {label} lock {path}: {exc}") from exc
