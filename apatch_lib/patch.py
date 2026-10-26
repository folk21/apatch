"""Validate a trusted handoff archive and apply only bounded repository paths."""

import hashlib
import io
import json
import logging
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path

from .core.paths import (PARAMS_MEMBER, REGISTRY_MEMBER, RUNTIME_METADATA_MEMBERS,
                         is_protected_runtime_path)
from .created_patches import parse_registry
from .gitutil import run
from .model import Abort, BASENAME_PATTERN, Config, Handoff, parse_handoff_payload, safe_relative

LOGGER = logging.getLogger("apatch.patch")


@dataclass(frozen=True)
class Archive:
    sha256: str
    changed: frozenset[str]
    created_registry: tuple[str, ...] | None = None
    embedded_handoff: Handoff | None = None


def patch_file(config: Config, handoff: Handoff) -> Path:
    return config.downloads / handoff.patch


def handoff_from_zip(config: Config, root: Path, name: str) -> Handoff:
    """Load a self-contained ZIP handoff without trusting extracted file contents."""
    if not BASENAME_PATTERN.fullmatch(name):
        raise Abort("ZIP selection must be an ASCII-safe filename")
    target = config.downloads / name
    if target.is_symlink() or not target.is_file():
        raise Abort(f"Selected ZIP is missing or unsafe: {target}")
    if target.stat().st_size > config.max_bytes:
        raise Abort("Compressed ZIP exceeds maximum configured size")
    try:
        with zipfile.ZipFile(target) as source:
            matches = [info for info in source.infolist()
                       if info.filename == f"{root.name}/{PARAMS_MEMBER}"]
            if len(matches) != 1:
                raise Abort("Self-contained ZIP must have exactly one reserved .apatch/params.json member")
            info = matches[0]
            kind = (info.external_attr >> 16) & 0o170000
            if info.is_dir() or kind not in (0, stat.S_IFREG) or info.file_size > 65536:
                raise Abort("Embedded handoff must be a regular JSON file of at most 64 KiB")
            payload = json.loads(source.read(info).decode("utf-8"))
    except (OSError, ValueError, UnicodeError, zipfile.BadZipFile) as exc:
        raise Abort(f"Cannot read embedded handoff parameters: {exc}") from exc
    handoff = parse_handoff_payload(payload, embedded=True)
    if handoff.patch != name or handoff.repository != root.name:
        raise Abort("Embedded handoff identity differs from selected ZIP or repository")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    verified = replace(handoff, patch_sha256=digest)
    inspected = inspect(config, verified, root, before_apply=False)
    if inspected.embedded_handoff is None:
        raise Abort("Missing verified embedded handoff metadata")
    return verified


def inspect(config: Config, handoff: Handoff, root: Path, *, before_apply: bool = True) -> Archive:
    target = patch_file(config, handoff)
    if not target.is_file() or target.is_symlink():
        raise Abort(f"Patch ZIP does not exist or is a symlink: {target}")
    if target.stat().st_size > config.max_bytes:
        raise Abort("Compressed ZIP exceeds maximum configured size")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if handoff.patch_sha256 and handoff.patch_sha256 != digest:
        raise Abort("Patch SHA-256 does not match the handoff file")
    changed = set()
    incoming_registry = None
    embedded_handoff = None
    metadata_seen = False
    params_seen = False
    total = 0
    try:
        with zipfile.ZipFile(target) as archive:
            members = archive.infolist()
            if len(members) > 5000 or sum(info.file_size for info in members) > config.max_bytes:
                raise Abort("Archive exceeds configured size or entry count")
            if archive.testzip() is not None:
                raise Abort("Corrupt ZIP member")
            for info in members:
                name = safe_relative(info.filename[:-1] if info.is_dir() else info.filename)
                parts = name.split("/", 1)
                if len(parts) != 2 or parts[0] != root.name:
                    if info.is_dir() and name == root.name:
                        continue
                    raise Abort(f"Archive entry outside {root.name}/: {name}")
                relative = safe_relative(parts[1])
                if is_protected_runtime_path(relative) and relative not in RUNTIME_METADATA_MEMBERS:
                    if not (info.is_dir() and relative == ".apatch"):
                        raise Abort(f"ZIP cannot modify protected apatch runtime path: {relative}")
                if info.is_dir():
                    continue
                total += info.file_size
                if total > config.max_bytes:
                    raise Abort("Archive exceeds maximum uncompressed size")
                kind = (info.external_attr >> 16) & 0o170000
                if kind not in (0, stat.S_IFREG):
                    raise Abort(f"Unsupported ZIP file type: {name}")
                if relative == REGISTRY_MEMBER:
                    if metadata_seen or relative in handoff.delete_paths:
                        raise Abort(f"Duplicate/conflicting created-patch metadata: {name}")
                    incoming_registry = parse_registry(archive.read(info), name)
                    metadata_seen = True
                    continue
                if relative == PARAMS_MEMBER:
                    if params_seen or relative in handoff.delete_paths:
                        raise Abort(f"Duplicate/conflicting handoff parameters metadata: {name}")
                    if info.file_size > 65536:
                        raise Abort("Embedded handoff parameters exceed 64 KiB")
                    try:
                        payload = json.loads(archive.read(info).decode("utf-8"))
                    except (ValueError, UnicodeError) as exc:
                        raise Abort(f"Invalid embedded handoff JSON: {exc}") from exc
                    embedded_handoff = parse_handoff_payload(payload, embedded=True)
                    if embedded_handoff.repository != root.name or embedded_handoff.patch != handoff.patch:
                        raise Abort("Embedded handoff repository or ZIP basename differs from the selected patch")
                    if embedded_handoff != handoff.__class__(
                            handoff.repository, handoff.branch, handoff.patch, handoff.message,
                            handoff.base_commit, None, handoff.delete_paths):
                        raise Abort("Embedded handoff metadata differs from selected handoff")
                    params_seen = True
                    continue
                if relative in changed or relative in handoff.delete_paths:
                    raise Abort(f"Duplicate/conflicting path: {relative}")
                changed.add(relative)
    except (OSError, zipfile.BadZipFile) as exc:
        raise Abort(f"Cannot read patch ZIP: {exc}") from exc
    if not changed and not handoff.delete_paths:
        raise Abort("Empty patch ZIP")
    planned_paths = changed | set(handoff.delete_paths)
    for relative in planned_paths:
        if is_protected_runtime_path(relative):
            raise Abort(f"ZIP cannot delete or modify protected apatch runtime path: {relative}")
        components = relative.split("/")
        for index in range(1, len(components)):
            parent = "/".join(components[:index])
            if parent in planned_paths:
                raise Abort(f"Conflicting ZIP paths: {parent} is an ancestor of {relative}")
        current = root
        parts = components
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
    return Archive(digest, frozenset(changed), incoming_registry, embedded_handoff)


def apply(config, handoff, root, archive_data):
    path = patch_file(config, handoff)
    snapshot = path.read_bytes()
    if hashlib.sha256(snapshot).hexdigest() != archive_data.sha256:
        raise Abort("ZIP bytes changed after validation")
    # Repeat filesystem checks immediately before extraction to catch changed parents.
    current = inspect(config, handoff, root)
    if current.sha256 != archive_data.sha256 or current.changed != archive_data.changed:
        raise Abort("ZIP contents changed since the application preflight")
    staged = []
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        try:
            # Prepare all file bytes before replacing any existing destination.
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative = info.filename.split("/", 1)[1]
                if relative in RUNTIME_METADATA_MEMBERS:
                    continue
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                existing_mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else None
                descriptor, temp_name = tempfile.mkstemp(dir=destination.parent, prefix=".apatch-")
                staged.append((temp_name, destination, relative))
                with os.fdopen(descriptor, "wb") as out, archive.open(info) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                zip_mode = (info.external_attr >> 16) & 0o777
                os.chmod(temp_name, existing_mode if existing_mode is not None else (0o755 if zip_mode & 0o111 else 0o644))
            for temp_name, destination, relative in staged:
                os.replace(temp_name, destination)
                LOGGER.info("patch file written path=%s", relative)
        except OSError as exc:
            raise Abort(f"Cannot stage or apply ZIP content: {exc}; inspect the applying checkpoint") from exc
        finally:
            for temp_name, _, _ in staged:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
    for relative in handoff.delete_paths:
        (root / relative).unlink()
        LOGGER.info("patch file removed path=%s", relative)
