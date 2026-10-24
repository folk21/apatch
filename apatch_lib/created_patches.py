"""Validate the optional ordered registry of patches generated for a project."""

import os
import stat
from pathlib import Path

from .model import Abort, BASENAME_PATTERN


REGISTRY_NAME = "created_patches.txt"
MAX_REGISTRY_BYTES = 16 * 1024 * 1024


def registry_path(root: Path) -> Path:
    return root / ".apatch" / REGISTRY_NAME


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
        content = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise Abort(f"[PATCH_ORDER] Cannot read UTF-8 created-patch registry {path}: {exc}") from exc

    names = []
    seen = set()
    for line_number, name in enumerate(content.splitlines(), start=1):
        if not BASENAME_PATTERN.fullmatch(name):
            raise Abort(f"[PATCH_ORDER] Invalid ZIP basename in {path} at line {line_number}")
        if name in seen:
            raise Abort(f"[PATCH_ORDER] Duplicate created patch {name} in {path} at line {line_number}")
        names.append(name)
        seen.add(name)
    return tuple(names)


def assert_patch_order(root: Path, patch_name: str, history) -> bool:
    """Reject applying a later generated patch before any missing predecessor."""
    names = read_registry(root)
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
