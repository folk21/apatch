"""External, atomic checkpoint storage; never an authority for Git operations."""

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
    with lock_file.open("a+b") as lock:
        os.chmod(lock_file, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise Abort(f"Invalid state file; inspect manually: {exc}") from exc
                if not isinstance(data, dict) or data.get("schema_version") != 1:
                    raise Abort("Invalid state file version")
            else:
                data = {"schema_version": 1, "workflows": {}}
            yield data
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


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
