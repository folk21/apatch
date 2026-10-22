"""Project-local, atomic checkpoint storage; never an authority for Git operations."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .model import Abort


@contextmanager
def locked_state(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.with_name(path.name + ".lock")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"State destination must be a regular file: {path}")
    if lock_file.is_symlink() or (lock_file.exists() and not lock_file.is_file()):
        raise Abort(f"State lock must be a regular file: {lock_file}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_file, flags, 0o600)
        with os.fdopen(descriptor, "r+b") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                if path.exists():
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError) as exc:
                        raise Abort(f"Invalid state file; inspect manually: {exc}") from exc
                    if (not isinstance(data, dict) or data.get("schema_version") != 1
                            or not isinstance(data.get("workflows"), dict)):
                        raise Abort("Invalid state file version")
                else:
                    data = {"schema_version": 1, "workflows": {}}
                yield data
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
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
