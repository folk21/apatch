"""Validate the optional ordered registry of patches generated for a project."""

import os
import stat
import fcntl
import tempfile
from pathlib import Path

from .model import Abort, BASENAME_PATTERN


REGISTRY_NAME = "created_patches.txt"
MAX_REGISTRY_BYTES = 16 * 1024 * 1024


def registry_path(root: Path) -> Path:
    return root / ".apatch" / REGISTRY_NAME


def parse_registry(raw: bytes, source: str) -> tuple[str, ...]:
    """Validate a UTF-8 registry using the same contract for disk and ZIP data."""
    if len(raw) > MAX_REGISTRY_BYTES:
        raise Abort(f"[PATCH_ORDER] Created-patch registry exceeds the size limit: {source}")
    try:
        content = raw.decode("utf-8")
    except UnicodeError as exc:
        raise Abort(f"[PATCH_ORDER] Cannot read UTF-8 created-patch registry {source}: {exc}") from exc
    names = []
    seen = set()
    for line_number, name in enumerate(content.splitlines(), start=1):
        if not BASENAME_PATTERN.fullmatch(name):
            raise Abort(f"[PATCH_ORDER] Invalid ZIP basename in {source} at line {line_number}")
        if name in seen:
            raise Abort(f"[PATCH_ORDER] Duplicate created patch {name} in {source} at line {line_number}")
        names.append(name)
        seen.add(name)
    return tuple(names)


def read_registry(root: Path) -> tuple[str, ...] | None:
    """Return ordered basenames or None when an older project has no registry."""
    directory = root / ".apatch"
    path = registry_path(root)
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise Abort(f"[PATCH_ORDER] Unsafe registry directory: {directory}")
    if path.is_symlink():
        raise Abort(f"[PATCH_ORDER] Created-patch registry must not be a symlink: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        if path.is_symlink():
            raise Abort(f"[PATCH_ORDER] Created-patch registry must not be a symlink: {path}")
        return None
    except OSError as exc:
        raise Abort(f"[PATCH_ORDER] Cannot open created-patch registry {path}: {exc}") from exc
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise Abort(f"[PATCH_ORDER] Created-patch registry must be a regular file: {path}")
            if info.st_size > MAX_REGISTRY_BYTES:
                raise Abort(f"[PATCH_ORDER] Created-patch registry exceeds the size limit: {path}")
            raw = handle.read(MAX_REGISTRY_BYTES + 1)
            if len(raw) > MAX_REGISTRY_BYTES:
                raise Abort(f"[PATCH_ORDER] Created-patch registry exceeds the size limit: {path}")
    except OSError as exc:
        raise Abort(f"[PATCH_ORDER] Cannot read created-patch registry {path}: {exc}") from exc
    return parse_registry(raw, str(path))


def _effective_registry(root: Path, incoming: tuple[str, ...] | None):
    existing = read_registry(root)
    if incoming is None:
        return existing
    if existing is not None and incoming[:len(existing)] != existing:
        raise Abort(f"[PATCH_ORDER] Incoming created-patch registry does not extend the "
                    f"existing prefix of {registry_path(root)}; refusing to overwrite history")
    return incoming


def assert_patch_order(root: Path, patch_name: str, history,
                       incoming: tuple[str, ...] | None = None) -> bool:
    """Reject applying a later generated patch before any missing predecessor."""
    names = _effective_registry(root, incoming)
    if names is None:
        return False
    path = registry_path(root)
    if patch_name not in names:
        raise Abort(f"[PATCH_ORDER] Patch {patch_name} is not registered in {path}. "
                    "Review the created-patch list before applying this ZIP.")
    for predecessor in names[:names.index(patch_name)]:
        if not history.contains(predecessor):
            raise Abort(f"[PATCH_ORDER] Patch {predecessor} has not been applied! "
                        f"Cannot apply {patch_name} before earlier generated patches. "
                        f"Created list: {path}. Applied journal: {history.path}. "
                        "Recovery: apply the missing patch or reconcile verified application history.")
    return True


def persist_registry(root: Path, incoming: tuple[str, ...] | None) -> bool:
    """Atomically install a validated append-only registry under a stable lock."""
    if incoming is None:
        return False
    path = registry_path(root)
    lock = path.with_name(path.name + ".lock")
    if lock.is_symlink() or (lock.exists() and not lock.is_file()):
        raise Abort(f"[PATCH_ORDER] Unsafe created-patch lock: {lock}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock, flags, 0o600)
        with os.fdopen(descriptor, "r+b") as handle:
            os.fchmod(handle.fileno(), 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                existing = read_registry(root)
                if existing is not None and incoming[:len(existing)] != existing:
                    raise Abort("[PATCH_ORDER] Created-patch registry changed since preflight; "
                                "existing entries cannot be removed or reordered")
                if existing == incoming:
                    return False
                data = "".join(f"{name}\n" for name in incoming).encode("utf-8")
                if len(data) > MAX_REGISTRY_BYTES:
                    raise Abort("[PATCH_ORDER] Created-patch registry exceeds the size limit")
                temporary = None
                try:
                    file_descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".created-patches-")
                    with os.fdopen(file_descriptor, "wb") as out:
                        os.fchmod(out.fileno(), 0o600)
                        out.write(data)
                        out.flush()
                        os.fsync(out.fileno())
                    os.replace(temporary, path)
                    directory_descriptor = os.open(path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_descriptor)
                    finally:
                        os.close(directory_descriptor)
                finally:
                    if temporary and os.path.exists(temporary):
                        os.unlink(temporary)
                return True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise Abort(f"[PATCH_ORDER] Cannot atomically update {path}: {exc}") from exc
