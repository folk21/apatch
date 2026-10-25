"""Project-local, atomic checkpoint storage; never an authority for Git operations."""

import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .model import Abort
from .operation_events import MAX_RUNS, OperationRun, validate_runs
from .storage.locking import exclusive_file_lock


STATE_SCHEMA_VERSION = 2
MAX_STATE_BYTES = 32 * 1024 * 1024


def _upgrade_and_validate(data):
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
            or data["schema_version"] not in {1, STATE_SCHEMA_VERSION}
            or not isinstance(data.get("workflows"), dict)):
        raise Abort("Invalid state file version or workflows")
    if data["schema_version"] == 1:
        if "operation_runs" in data:
            raise Abort("Schema-v1 state must not contain a v2 operation journal")
        data = dict(data, schema_version=STATE_SCHEMA_VERSION, operation_runs=[])
    validate_runs(data.get("operation_runs"))
    return data


def read_state_snapshot(path: Path):
    """Read a checkpoint without creating locks, directories, or state files."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"State source must be a regular file: {path}")
    if not path.exists():
        return {"schema_version": STATE_SCHEMA_VERSION, "workflows": {}, "operation_runs": []}
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise Abort(f"State source must be a regular file: {path}")
            if os.fstat(handle.fileno()).st_size > MAX_STATE_BYTES:
                raise Abort("State file is unexpectedly large; inspect manually")
            data = json.load(handle)
    except (OSError, ValueError, UnicodeError) as exc:
        raise Abort(f"Invalid state file; inspect manually: {exc}") from exc
    return _upgrade_and_validate(data)


@contextmanager
def locked_state(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.with_name(path.name + ".lock")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"State destination must be a regular file: {path}")
    if lock_file.is_symlink() or (lock_file.exists() and not lock_file.is_file()):
        raise Abort(f"State lock must be a regular file: {lock_file}")
    try:
        with exclusive_file_lock(lock_file, label="state", wait_seconds=10):
            yield read_state_snapshot(path)
    except OSError as exc:
        raise Abort(f"Cannot access state lock {lock_file}: {exc}") from exc


def save(path: Path, data: dict):
    """Atomic replacement; callers already own the project's state lock."""
    upgraded = _upgrade_and_validate(data)
    if upgraded is not data:
        data.clear()
        data.update(upgraded)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"State destination must be a regular file: {path}")
    serialized = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(serialized.encode("utf-8")) > MAX_STATE_BYTES:
        raise Abort("State journal reached 32 MiB; archive it explicitly before continuing")
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".apatch-state-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def start_run(path: Path, state: dict, operation: OperationRun):
    """Persist a new STARTED record under the caller's existing state lock."""
    upgraded = _upgrade_and_validate(state)
    if upgraded is not state:
        state.clear()
        state.update(upgraded)
    runs = state.setdefault("operation_runs", [])
    if len(runs) >= MAX_RUNS:
        raise Abort("Operation journal reached its limit; explicit archival is required")
    if any(prior["run_id"] == operation.data["run_id"] for prior in runs):
        raise Abort("Duplicate operation run ID")
    runs.append(operation.data)
    try:
        save(path, state)
    except Exception:
        runs.pop()
        raise
    return operation.data["run_id"]


def finish_run(path: Path, state: dict, run_id: str, *, outcome: str,
               before=None, after=None, verified_facts=None):
    """Complete exactly one STARTED run; never rewrite another attempt."""
    runs = state["operation_runs"]
    matches = [index for index, item in enumerate(runs) if item["run_id"] == run_id]
    if len(matches) != 1:
        raise Abort("Cannot locate unique operation run to finish")
    index = matches[0]
    prior = runs[index]
    runs[index] = OperationRun.finish(prior, outcome=outcome, before=before,
                                      after=after, verified_facts=verified_facts)
    try:
        save(path, state)
    except Exception:
        runs[index] = prior
        raise
