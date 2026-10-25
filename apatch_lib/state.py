"""Project-local, atomic checkpoint storage; never an authority for Git operations."""

import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .model import Abort
from .storage.locking import exclusive_file_lock


def read_state_snapshot(path: Path):
    """Read a checkpoint without creating locks, directories, or state files."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"State source must be a regular file: {path}")
    if not path.exists():
        return {"schema_version": 1, "workflows": {}}
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise Abort(f"State source must be a regular file: {path}")
            if os.fstat(handle.fileno()).st_size > 32 * 1024 * 1024:
                raise Abort("State file is unexpectedly large; inspect manually")
            data = json.load(handle)
    except (OSError, ValueError, UnicodeError) as exc:
        raise Abort(f"Invalid state file; inspect manually: {exc}") from exc
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or not isinstance(data.get("workflows"), dict)):
        raise Abort("Invalid state file version")
    return data


@contextmanager
def locked_state(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.with_name(path.name + ".lock")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"State destination must be a regular file: {path}")
    if lock_file.is_symlink() or (lock_file.exists() and not lock_file.is_file()):
        raise Abort(f"State lock must be a regular file: {lock_file}")
    try:
        with exclusive_file_lock(lock_file, label="state"):
            yield read_state_snapshot(path)
    except OSError as exc:
        raise Abort(f"Cannot access state lock {lock_file}: {exc}") from exc


def save(path: Path, data: dict):
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".apatch-state-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
