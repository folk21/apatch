"""Conservative private review retention and metadata-only diagnostic export.

This module never changes Git, review verdicts, or canonical-check evidence.
"""

import fcntl
import hashlib
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .model import Abort
from .review_evidence_api import (_REVIEW_ID, _PROVIDER_ID, _SHA256, _directory,
                                  _json_file, _private_file,
                                  _verify_private_digest)

_MAX_MANIFEST = 131072
_MAX_ENTRIES = 512
_LOCK_NAME = ".retention.lock"
_PRUNE_MARKER = ".prune-intent.json"
_PRUNING_ID = re.compile(r"pruning-([a-f0-9]{24})\Z")


def _error(message: str) -> Abort:
    return Abort("REVIEW_RETENTION_UNSAFE: " + message)


def _private_stat(fd: int, name: str) -> os.stat_result:
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except OSError as exc:
        raise _error("Missing private evidence member") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1):
        raise _error("Evidence contains a non-private, linked, or non-regular member")
    return info


def _hash_file(fd: int, name: str, size: int, digest: str) -> None:
    if (type(size) is not int or size < 0 or size > 67108864
            or type(digest) is not str or not _SHA256.fullmatch(digest)):
        raise _error("Invalid evidence size or digest")
    _private_stat(fd, name)
    try:
        _verify_private_digest(fd, name, size, digest)
    except Abort as exc:
        raise _error("Evidence member digest differs from its manifest") from exc


def _file_record(fd: int, name: str, limit: int = 67108864) -> dict:
    info = _private_stat(fd, name)
    if info.st_size > limit:
        raise _error("Evidence member exceeds its size bound")
    raw = _private_file(fd, name, limit)
    return {"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _recorded_members(fd: int, review_id: str) -> tuple[dict, tuple[dict, ...]]:
    manifest = _json_file(fd, "manifest.json", _MAX_MANIFEST)
    if (manifest.get("schema_version") != 1 or manifest.get("review_id") != review_id
            or manifest.get("status") not in {"COMPLETED", "FAILED"}
            or type(manifest.get("snapshot")) is not list or len(manifest["snapshot"]) != 5):
        raise _error("Unknown or incomplete review manifest")
    providers = manifest.get("providers")
    contexts = manifest.get("contexts", [])
    if (type(providers) is not list or len(providers) > 8
            or type(contexts) is not list or len(contexts) > 8):
        raise _error("Unbounded provider or context manifest")
    files = [_file_record(fd, "manifest.json", _MAX_MANIFEST)]
    names = {"manifest.json"}
    seen_providers = set()

    def add(name: str, size: int, digest: str):
        if (type(name) is not str or name in names or "/" in name or "\\" in name):
            raise _error("Duplicate or unsafe evidence member")
        names.add(name)
        _hash_file(fd, name, size, digest)
        files.append({"name": name, "bytes": size, "sha256": digest})

    for provider in providers:
        if type(provider) is not dict:
            raise _error("Invalid provider metadata")
        pid = provider.get("id")
        if (type(pid) is not str or not _PROVIDER_ID.fullmatch(pid)
                or pid in seen_providers or provider.get("kind") not in {"llm", "script"}):
            raise _error("Invalid provider identity")
        if (type(provider.get("exit_code")) is not int
                or not -255 <= provider["exit_code"] <= 255
                or type(provider.get("timed_out")) is not bool
                or type(provider.get("truncated")) is not bool):
            raise _error("Invalid provider outcome")
        seen_providers.add(pid)
        for stream in ("stdout", "stderr"):
            filename = pid + "." + stream
            if provider.get(stream + "_file") != filename:
                raise _error("Unexpected evidence stream path")
            add(filename, provider.get(stream + "_bytes"), provider.get(stream + "_sha256"))
        if "normalized_file" in provider:
            normalized = pid + ".normalized.json"
            if provider["normalized_file"] != normalized:
                raise _error("Unexpected normalized report path")
            entry = _file_record(fd, normalized, 1048576)
            if entry["sha256"] != provider.get("normalized_sha256"):
                raise _error("Normalized report changed")
            add(normalized, entry["bytes"], entry["sha256"])
    for context in contexts:
        if type(context) is not dict:
            raise _error("Invalid context index")
        pid = context.get("provider_id")
        if type(pid) is not str or pid not in seen_providers or context.get("file") != pid + ".context.json":
            raise _error("Unknown indexed context")
        add(context["file"], context.get("bytes"), context.get("sha256"))
    actual = set(os.listdir(fd))
    if actual != names:
        raise _error("Unexpected, missing, or incomplete evidence members")
    return manifest, tuple(files)


@contextmanager
def review_storage_lock(root: Path):
    """Lock a single project storage root; reject symlink traversal and unsafe locks."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise _error("Secure review storage requires POSIX no-follow descriptors")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptors = [root_fd]
    try:
        apatch_fd = _directory(root_fd, ".apatch")
        descriptors.append(apatch_fd)
        reviews_fd = _directory(apatch_fd, "reviews", private=True)
        descriptors.append(reviews_fd)
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            lock_fd = os.open(_LOCK_NAME, flags, 0o600, dir_fd=reviews_fd)
        except OSError as exc:
            raise _error("Cannot open private retention lock") from exc
        descriptors.append(lock_fd)
        if (not stat.S_ISREG(os.fstat(lock_fd).st_mode)
                or stat.S_IMODE(os.fstat(lock_fd).st_mode) != 0o600
                or os.fstat(lock_fd).st_nlink != 1):
            raise _error("Retention lock is not a private regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield reviews_fd
    except OSError as exc:
        raise _error("Cannot access locked review storage") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


@dataclass(frozen=True)
class RetentionResult:
    """A bounded account of eligible deletion and protected unknown histories."""

    removed: tuple[str, ...]
    protected: tuple[str, ...]
    total_bytes: int
    total_runs: int
    dry_run: bool


def _marker_bytes(review_id: str, files: tuple[dict, ...]) -> bytes:
    body = {"schema_version": 1, "review_id": review_id, "files": list(files)}
    raw = (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(raw) > _MAX_MANIFEST:
        raise _error("Pruning intent is oversized")
    return raw


def _recover_marked(reviews_fd: int, dirname: str, *, preview: bool = False) -> None:
    """Finish a previously journaled deletion, refusing any unrecorded files."""
    match = _PRUNING_ID.fullmatch(dirname)
    original = "review-" + match.group(1) if match else dirname
    if not _REVIEW_ID.fullmatch(original):
        raise _error("Invalid pruning directory identity")
    run_fd = _directory(reviews_fd, dirname, private=True)
    try:
        marker = _json_file(run_fd, _PRUNE_MARKER, _MAX_MANIFEST)
        files = marker.get("files")
        if (marker.get("schema_version") != 1 or marker.get("review_id") != original
                or type(files) is not list or not 1 <= len(files) <= 28):
            raise _error("Invalid pruning journal")
        expected = set()
        for item in files:
            if (type(item) is not dict or set(item) != {"name", "bytes", "sha256"}
                    or type(item["name"]) is not str
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}\.(?:stdout|stderr|normalized\.json|context\.json)|manifest\.json", item["name"])
                    or item["name"] in expected):
                raise _error("Malformed pruning member inventory")
            expected.add(item["name"])
        if "manifest.json" not in expected:
            raise _error("Pruning journal has no manifest")
        actual = set(os.listdir(run_fd))
        if not actual <= expected | {_PRUNE_MARKER} or _PRUNE_MARKER not in actual:
            raise _error("Unknown file appeared during interrupted pruning")
        for item in files:
            if item["name"] in actual:
                _hash_file(run_fd, item["name"], item["bytes"], item["sha256"])
        if preview:
            return
        if not match:
            os.rename(dirname, "pruning-" + original.removeprefix("review-"),
                      src_dir_fd=reviews_fd, dst_dir_fd=reviews_fd)
        for item in files:
            if item["name"] in actual:
                _private_stat(run_fd, item["name"])
                os.unlink(item["name"], dir_fd=run_fd)
        os.unlink(_PRUNE_MARKER, dir_fd=run_fd)
    finally:
        os.close(run_fd)
    os.rmdir("pruning-" + original.removeprefix("review-"), dir_fd=reviews_fd)


def _delete_known_run(reviews_fd: int, review_id: str, files: tuple[dict, ...]) -> None:
    """Journal an exact cleanup scope before unlinking; interrupted cleanup is resumable."""
    run_fd = _directory(reviews_fd, review_id, private=True)
    try:
        if set(os.listdir(run_fd)) != {item["name"] for item in files}:
            raise _error("Review changed before pruning")
        for entry in files:
            _hash_file(run_fd, entry["name"], entry["bytes"], entry["sha256"])
        marker = _marker_bytes(review_id, files)
        flags = os.O_WRONLY | os.O_EXCL | os.O_CREAT | os.O_NOFOLLOW
        descriptor = os.open(_PRUNE_MARKER, flags, 0o600, dir_fd=run_fd)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(marker)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(run_fd)
    finally:
        os.close(run_fd)
    _recover_marked(reviews_fd, review_id)


def _retention_locked(reviews_fd: int, *, max_runs: int, max_bytes: int,
                      max_age_days: int, dry_run: bool, reserve_runs: int = 0,
                      reserve_bytes: int = 0, now: float | None = None) -> RetentionResult:
    if (any(type(v) is not int for v in (max_runs, max_bytes, max_age_days, reserve_runs, reserve_bytes))
            or not 1 <= max_runs <= 10000 or not 1048576 <= max_bytes <= 10737418240
            or not 1 <= max_age_days <= 3650 or reserve_runs < 0 or reserve_bytes < 0):
        raise Abort("REVIEW_RETENTION_POLICY: Invalid limits")
    now = time.time() if now is None else now
    eligible = []
    protected = []
    total_bytes = 0
    total_runs = 0
    entries = os.listdir(reviews_fd)
    if len(entries) > _MAX_ENTRIES:
        raise _error("Review store exceeds inspection entry bound")
    for name in entries:
        if name == _LOCK_NAME:
            continue
        if _PRUNING_ID.fullmatch(name):
            try:
                _recover_marked(reviews_fd, name, preview=dry_run)
            except (Abort, OSError, ValueError, KeyError, TypeError):
                protected.append(name)
            continue
        if _REVIEW_ID.fullmatch(name):
            try:
                pending_fd = _directory(reviews_fd, name, private=True)
                try:
                    has_marker = _PRUNE_MARKER in os.listdir(pending_fd)
                finally:
                    os.close(pending_fd)
                if has_marker:
                    _recover_marked(reviews_fd, name, preview=dry_run)
                    continue
            except (Abort, OSError, ValueError, KeyError, TypeError):
                protected.append(name)
                continue
        if not _REVIEW_ID.fullmatch(name):
            protected.append(name)
            continue
        total_runs += 1
        try:
            info = os.stat(name, dir_fd=reviews_fd, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
                raise _error("Unsafe review directory")
            run_fd = _directory(reviews_fd, name, private=True)
            try:
                _, files = _recorded_members(run_fd, name)
            finally:
                os.close(run_fd)
            bytes_used = sum(item["bytes"] for item in files)
            eligible.append((name, info.st_mtime, bytes_used, files))
            total_bytes += bytes_used
        except (Abort, OSError, ValueError, KeyError, TypeError):
            protected.append(name)
    selected = []
    runs = total_runs + reserve_runs
    used = total_bytes + reserve_bytes
    for name, modified, bytes_used, files in sorted(eligible, key=lambda item: (item[1], item[0])):
        if (modified > now - max_age_days * 86400
                and runs <= max_runs and used <= max_bytes):
            continue
        selected.append((name, files))
        runs -= 1
        used -= bytes_used
    if not dry_run:
        for name, files in selected:
            _delete_known_run(reviews_fd, name, files)
    return RetentionResult(tuple(name for name, _ in selected), tuple(sorted(protected)),
                           used, runs, dry_run)


def prune_review_artifacts(root: Path, *, max_runs: int = 100,
                           max_bytes: int = 536870912, max_age_days: int = 30,
                           dry_run: bool = True) -> RetentionResult:
    """Explicit opt-in pruning; previews are non-destructive by default."""
    with review_storage_lock(root) as reviews_fd:
        return _retention_locked(reviews_fd, max_runs=max_runs, max_bytes=max_bytes,
                                 max_age_days=max_age_days, dry_run=dry_run)


def export_review_summary(root: Path, review_id: str, *, consent: bool = False) -> bytes:
    """Return verified metadata references only, never source text or raw output."""
    if not consent:
        raise Abort("REVIEW_EXPORT_CONSENT: Explicit export consent is required")
    if type(review_id) is not str or not _REVIEW_ID.fullmatch(review_id):
        raise Abort("REVIEW_EXPORT_UNKNOWN: Invalid review identity")
    descriptors = []
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(root_fd)
        apatch_fd = _directory(root_fd, ".apatch")
        descriptors.append(apatch_fd)
        reviews_fd = _directory(apatch_fd, "reviews", private=True)
        descriptors.append(reviews_fd)
        review_fd = _directory(reviews_fd, review_id, private=True)
        descriptors.append(review_fd)
        manifest, files = _recorded_members(review_fd, review_id)
    except (OSError, Abort, KeyError, TypeError, ValueError) as exc:
        raise Abort("REVIEW_EXPORT_UNKNOWN: Private review is missing or incomplete") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    providers = []
    for provider in manifest["providers"]:
        providers.append({"id": provider["id"], "kind": provider["kind"],
                          "exit_code": provider["exit_code"],
                          "timed_out": provider["timed_out"],
                          "truncated": provider["truncated"],
                          "has_normalized": "normalized_file" in provider})
    body = {"schema_version": 1, "review_id": review_id,
            "status": manifest["status"], "providers": providers,
            "evidence_ref": ".apatch/reviews/" + review_id,
            "manifest_sha256": next(file["sha256"] for file in files if file["name"] == "manifest.json")}
    payload = (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > 8192:
        raise Abort("REVIEW_EXPORT_UNKNOWN: Summary exceeds export limit")
    return payload
