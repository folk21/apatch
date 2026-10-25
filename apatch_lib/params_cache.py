"""Validate and atomically persist the current project handoff parameters."""

import fcntl
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .model import Abort, parse_handoff_payload


MAX_PARAMS_BYTES = 65536
PARAMS_NAME = "params.json"


def cache_path(root: Path) -> Path:
    directory = root / ".apatch"
    if directory.is_symlink() or not directory.is_dir():
        raise Abort("Project .apatch directory must be a real directory")
    return directory / PARAMS_NAME


def _require_regular(path: Path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"Unsafe cached handoff path: {path}")


def _payload(handoff):
    payload = {
        "schema_version": 1,
        "repository": handoff.repository,
        "feature_branch": handoff.branch,
        "patch_file": handoff.patch,
        "commit_message": handoff.message,
        "patch_sha256": handoff.patch_sha256,
    }
    if handoff.base_commit:
        payload["base_commit"] = handoff.base_commit
    if handoff.delete_paths:
        payload["delete_paths"] = list(handoff.delete_paths)
    return payload


def load_cached_handoff(root: Path):
    """Read-only loading; no lock or cache creation during STS or other queries."""
    path = cache_path(root)
    _require_regular(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_PARAMS_BYTES:
                raise Abort("Cached parameters are not a bounded regular file")
            data = json.loads(stream.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise Abort(f"Cannot read .apatch/params.json; select a handoff explicitly: {exc}") from exc
    handoff = parse_handoff_payload(data)
    if handoff.repository != root.name or not handoff.patch_sha256:
        raise Abort("Cached parameters have the wrong repository or no verified ZIP digest")
    return handoff


@contextmanager
def _locked_cache(root: Path):
    path = cache_path(root)
    lock_path = path.with_name(path.name + ".lock")
    _require_regular(path)
    _require_regular(lock_path)
    fd = None
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "r+b") as handle:
            fd = None
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise Abort("Cached parameters lock must be regular")
            os.fchmod(handle.fileno(), 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield path
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (OSError, BlockingIOError) as exc:
        raise Abort(f"Cannot lock .apatch/params.json: {exc}") from exc
    finally:
        if fd is not None:
            os.close(fd)


def save_cached_handoff(root: Path, handoff):
    """Write only a previously validated ZIP handoff using atomic replacement."""
    if handoff.repository != root.name or not handoff.patch_sha256:
        raise Abort("Refusing to cache a handoff without verified identity and digest")
    serialized = (json.dumps(_payload(handoff), ensure_ascii=False, indent=2,
                             sort_keys=True) + "\n").encode("utf-8")
    if len(serialized) > MAX_PARAMS_BYTES:
        raise Abort("Cached handoff parameters exceed 64 KiB")
    with _locked_cache(root) as path:
        if path.exists():
            load_cached_handoff(root)
        descriptor, temporary = tempfile.mkstemp(prefix=".apatch-params-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            _require_regular(path)
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
