"""Validate and atomically persist the current project handoff parameters."""

import json
import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .model import Abort, parse_handoff_payload
from .storage.locking import exclusive_file_lock


MAX_PARAMS_BYTES = 65536
PARAMS_NAME = "params.json"


class RecoverableCacheError(Abort):
    """A bounded, readable cache has invalid legacy or corrupt handoff content."""


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
    except OSError as exc:
        raise Abort(f"Cannot read .apatch/params.json; select a handoff explicitly: {exc}") from exc
    except (ValueError, UnicodeError) as exc:
        raise RecoverableCacheError(
            f"Cannot read .apatch/params.json; select a handoff explicitly: {exc}") from exc
    try:
        handoff = parse_handoff_payload(data)
    except Abort as exc:
        raise RecoverableCacheError(f"Invalid cached handoff parameters: {exc}") from exc
    if handoff.repository != root.name or not handoff.patch_sha256:
        raise RecoverableCacheError(
            "Cached parameters have the wrong repository or no verified ZIP digest")
    return handoff


@contextmanager
def _locked_cache(root: Path):
    path = cache_path(root)
    lock_path = path.with_name(path.name + ".lock")
    _require_regular(path)
    _require_regular(lock_path)
    with exclusive_file_lock(lock_path, label="cached handoff parameters"):
        yield path


def _recovery_backup_directory(path: Path) -> Path:
    """Validate the backup location without following an existing symlink."""
    backups = path.parent / "backups"
    if backups.is_symlink() or (backups.exists() and not backups.is_dir()):
        raise Abort(f"Unsafe cached handoff backup directory: {backups}")
    return backups


def preflight_cache_write(root: Path) -> None:
    """Reject unsafe cache recovery targets before a ZIP changes source files."""
    path = cache_path(root)
    _require_regular(path)
    if not path.exists():
        return
    if path.stat().st_size > MAX_PARAMS_BYTES:
        raise Abort("Cached parameters exceed 64 KiB; inspect them before recovery")
    try:
        load_cached_handoff(root)
    except RecoverableCacheError:
        _require_regular(path)
        if path.stat().st_size > MAX_PARAMS_BYTES:
            raise Abort("Cached parameters exceed 64 KiB; inspect them before recovery")
        _recovery_backup_directory(path)


def _preserve_invalid_cache(path: Path) -> Path:
    """Hard-link the exact stale file before replacing it with a verified handoff."""
    backups = _recovery_backup_directory(path)
    backups.mkdir(mode=0o700, exist_ok=True)
    _recovery_backup_directory(path)
    _require_regular(path)
    for _ in range(5):
        destination = backups / f"params-invalid-{uuid.uuid4().hex}.json"
        try:
            os.link(path, destination, follow_symlinks=False)
        except FileExistsError:
            continue
        except OSError as exc:
            raise Abort(f"Cannot preserve invalid cached parameters: {exc}") from exc
        directory_fd = os.open(backups, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination
    raise Abort("Cannot reserve a unique invalid-cache backup filename")


def save_cached_handoff(root: Path, handoff):
    """Write only a previously validated ZIP handoff using atomic replacement."""
    if handoff.repository != root.name or not handoff.patch_sha256:
        raise Abort("Refusing to cache a handoff without verified identity and digest")
    serialized = (json.dumps(_payload(handoff), ensure_ascii=False, indent=2,
                             sort_keys=True) + "\n").encode("utf-8")
    if len(serialized) > MAX_PARAMS_BYTES:
        raise Abort("Cached handoff parameters exceed 64 KiB")
    with _locked_cache(root) as path:
        invalid_cache = False
        if path.exists():
            if path.stat().st_size > MAX_PARAMS_BYTES:
                raise Abort("Cached parameters exceed 64 KiB; inspect them before recovery")
            try:
                load_cached_handoff(root)
            except RecoverableCacheError:
                _require_regular(path)
                if path.stat().st_size > MAX_PARAMS_BYTES:
                    raise Abort("Cached parameters exceed 64 KiB; inspect them before recovery")
                _recovery_backup_directory(path)
                invalid_cache = True
        descriptor, temporary = tempfile.mkstemp(prefix=".apatch-params-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            _require_regular(path)
            if invalid_cache:
                backup = _preserve_invalid_cache(path)
                print(f"WARNING: Invalid cached parameters preserved at {backup}")
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
