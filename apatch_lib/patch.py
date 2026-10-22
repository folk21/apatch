"""Validate a trusted handoff archive and apply only bounded repository paths."""

import hashlib
import io
import logging
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .gitutil import run
from .model import Abort, safe_relative

LOGGER = logging.getLogger("apatch.patch")


@dataclass(frozen=True)
class Archive:
    sha256: str
    changed: frozenset[str]


def patch_file(config, handoff):
    return config.downloads / handoff.patch


def inspect(config, handoff, root, *, before_apply=True):
    target = patch_file(config, handoff)
    if not target.is_file() or target.is_symlink():
        raise Abort(f"Patch ZIP does not exist or is a symlink: {target}")
    if target.stat().st_size > config.max_bytes:
        raise Abort("Compressed ZIP exceeds maximum configured size")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if handoff.patch_sha256 and handoff.patch_sha256 != digest:
        raise Abort("Patch SHA-256 does not match the handoff file")
    changed = set()
    total = 0
    try:
        with zipfile.ZipFile(target) as archive:
            members = archive.infolist()
            if len(members) > 5000 or sum(info.file_size for info in members) > config.max_bytes:
                raise Abort("Archive exceeds configured size or entry count")
            if archive.testzip() is not None:
                raise Abort("Corrupt ZIP member")
            for info in members:
                if info.is_dir():
                    continue
                total += info.file_size
                if total > config.max_bytes:
                    raise Abort("Archive exceeds maximum uncompressed size")
                name = safe_relative(info.filename)
                parts = name.split("/", 1)
                if len(parts) != 2 or parts[0] != root.name:
                    raise Abort(f"Archive entry outside {root.name}/: {name}")
                relative = safe_relative(parts[1])
                kind = (info.external_attr >> 16) & 0o170000
                if kind not in (0, stat.S_IFREG):
                    raise Abort(f"Unsupported ZIP file type: {name}")
                if relative in changed or relative in handoff.delete_paths:
                    raise Abort(f"Duplicate/conflicting path: {relative}")
                changed.add(relative)
    except (OSError, zipfile.BadZipFile) as exc:
        raise Abort(f"Cannot read patch ZIP: {exc}") from exc
    if not changed and not handoff.delete_paths:
        raise Abort("Empty patch ZIP")
    for relative in changed | set(handoff.delete_paths):
        current = root
        parts = relative.split("/")
        for item in parts[:-1]:
            current = current / item
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                raise Abort(f"Unsafe parent directory: {relative}")
        dest = root / relative
        if dest.is_symlink() or (dest.exists() and not dest.is_file()):
            raise Abort(f"Unsafe destination: {relative}")
    for relative in handoff.delete_paths:
        if before_apply and not (root / relative).is_file():
            raise Abort(f"Deletion target is missing: {relative}")
        run(["git", "ls-files", "--error-unmatch", "--", relative], root)
    LOGGER.info("patch inspected name=%s sha256=%s files=%d deletions=%d",
                handoff.patch, digest, len(changed), len(handoff.delete_paths))
    return Archive(digest, frozenset(changed))


def apply(config, handoff, root, archive_data):
    path = patch_file(config, handoff)
    snapshot = path.read_bytes()
    if hashlib.sha256(snapshot).hexdigest() != archive_data.sha256:
        raise Abort("ZIP bytes changed after validation")
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = info.filename.split("/", 1)[1]
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            existing_mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else None
            descriptor, temp_name = tempfile.mkstemp(dir=destination.parent, prefix=".apatch-")
            try:
                with os.fdopen(descriptor, "wb") as out, archive.open(info) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                zip_mode = (info.external_attr >> 16) & 0o777
                os.chmod(temp_name, existing_mode if existing_mode is not None else (0o755 if zip_mode & 0o111 else 0o644))
                os.replace(temp_name, destination)
                LOGGER.info("patch file written path=%s", relative)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
    for relative in handoff.delete_paths:
        (root / relative).unlink()
        LOGGER.info("patch file removed path=%s", relative)
