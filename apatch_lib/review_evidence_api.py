"""Read-only, quota-bound source excerpts for verified review findings."""

import hashlib
import json
import os
import re
import stat
import threading
from pathlib import Path
from typing import Callable

from .model import Abort, safe_relative


_REVIEW_ID = re.compile(r"review-[a-f0-9]{24}\Z")
_FINDING_ID = re.compile(r"[a-f0-9]{24}\Z")
_PROVIDER_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_MANIFEST_BYTES = 131072
_MAX_NORMALIZED_BYTES = 1048576


def _encoded(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _unknown(reason: str) -> Abort:
    return Abort("REVIEW_EVIDENCE_UNKNOWN: " + reason)


def _directory(parent: int, name: str, *, private: bool = False) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISDIR(mode) or (private and stat.S_IMODE(mode) != 0o700):
            os.close(descriptor)
            raise _unknown("Review storage directory is unsafe")
        return descriptor
    except OSError as exc:
        raise _unknown("Review storage directory is unavailable") from exc


def _private_file(parent: int, name: str, limit: int) -> bytes:
    if (not isinstance(name, str) or "/" in name or "\\" in name or
            name in {"", ".", ".."}):
        raise _unknown("Unsafe evidence filename")
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise _unknown("Evidence file is not a private regular file")
            if info.st_size > limit:
                raise _unknown("Evidence file is oversized")
            content = stream.read(limit + 1)
            if len(content) > limit or os.fstat(stream.fileno()).st_size != len(content):
                raise _unknown("Evidence file changed while reading")
            return content
    except OSError as exc:
        raise _unknown("Evidence file is unavailable") from exc


def _verify_private_digest(parent: int, name: str, expected_size: int, expected_hash: str) -> None:
    if (type(expected_size) is not int or not 0 <= expected_size <= 67108864):
        raise _unknown("Invalid raw evidence size")
    if type(expected_hash) is not str or not _SHA256.fullmatch(expected_hash):
        raise _unknown("Invalid raw evidence digest")
    if not isinstance(name, str) or "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise _unknown("Unsafe evidence filename")
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_size != expected_size):
                raise _unknown("Raw evidence file size or type changed")
            digest = hashlib.sha256()
            total = 0
            for chunk in iter(lambda: stream.read(65536), b""):
                total += len(chunk)
                if total > expected_size:
                    raise _unknown("Raw evidence size changed while reading")
                digest.update(chunk)
            if total != expected_size or digest.hexdigest() != expected_hash:
                raise _unknown("Raw evidence digest mismatch")
    except OSError as exc:
        raise _unknown("Raw evidence is unavailable") from exc


def _unique_members(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _unknown("Duplicate evidence metadata member")
        result[key] = value
    return result


def _nonfinite(_: str) -> None:
    raise _unknown("Nonfinite evidence metadata number")


def _json_data(content: bytes) -> object:
    try:
        return json.loads(content.decode("utf-8", "strict"),
                          object_pairs_hook=_unique_members, parse_constant=_nonfinite)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise _unknown("Evidence metadata is malformed") from exc


def _json_file(parent: int, name: str, limit: int) -> dict:
    content = _private_file(parent, name, limit)
    data = _json_data(content)
    if type(data) is not dict:
        raise _unknown("Evidence metadata must be an object")
    return data


def _source_excerpt(root_fd: int, path: str, line: int, context_lines: int) -> tuple[list[dict], str]:
    if (type(path) is not str or len(path) > 512 or ":" in path or "%" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise _unknown("Unsafe source path")
    try:
        safe_relative(path)
    except Abort as exc:
        raise _unknown("Unsafe source path") from exc
    if any(part in {".apatch", ".git"} for part in path.split("/")):
        raise _unknown("Private runtime and Git paths are not source evidence")
    parts = path.split("/")
    descriptors = []
    try:
        parent = root_fd
        for item in parts[:-1]:
            parent = _directory(parent, item)
            descriptors.append(parent)
        try:
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=parent)
        except OSError as exc:
            raise _unknown("Source file is unavailable") from exc
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_SOURCE_BYTES:
                raise _unknown("Source is not a bounded regular file")
            try:
                data = stream.read(_MAX_SOURCE_BYTES + 1)
            except OSError as exc:
                raise _unknown("Cannot read source file") from exc
            after = os.fstat(stream.fileno())
            if (len(data) > _MAX_SOURCE_BYTES or len(data) != before.st_size or
                    (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
                raise _unknown("Source changed while reading")
        try:
            lines = data.decode("utf-8", "strict").splitlines()
        except UnicodeError as exc:
            raise _unknown("Source is not UTF-8 text") from exc
        if line > len(lines):
            raise _unknown("Finding line is absent from the source")
        first = max(1, line - context_lines)
        last = min(len(lines), line + context_lines)
        return ([{"number": index, "text": lines[index - 1]}
                 for index in range(first, last + 1)], hashlib.sha256(data).hexdigest())
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


class ReviewEvidenceSession:
    """A single snapshot-scoped retrieval budget; never launches tools or writes data."""

    def __init__(self, root: Path, review_id: str, snapshot: tuple,
                 snapshot_reader: Callable[[], tuple], *, max_requests: int = 4,
                 max_response_bytes: int = 8192, max_total_bytes: int = 16384):
        if (type(review_id) is not str or not _REVIEW_ID.fullmatch(review_id)
                or type(snapshot) is not tuple or len(snapshot) != 5
                or not callable(snapshot_reader)):
            raise _unknown("Invalid review identity or snapshot reader")
        if (type(max_requests) is not int or not 1 <= max_requests <= 8
                or type(max_response_bytes) is not int or not 1024 <= max_response_bytes <= 8192
                or type(max_total_bytes) is not int or not 8192 <= max_total_bytes <= 65536):
            raise Abort("REVIEW_EVIDENCE_BUDGET: Invalid retrieval limits")
        self.root = root.resolve(strict=True)
        self.review_id = review_id
        self.snapshot = snapshot
        self.snapshot_reader = snapshot_reader
        self.max_requests = max_requests
        self.max_response_bytes = max_response_bytes
        self.max_total_bytes = max_total_bytes
        self.requests = 0
        self.bytes_returned = 0
        self._lock = threading.Lock()

    def _verified_finding(self, review_fd: int, finding_id: str) -> tuple[dict, dict, str, str]:
        manifest = _json_file(review_fd, "manifest.json", _MAX_MANIFEST_BYTES)
        if (type(manifest.get("schema_version")) is not int or
                manifest.get("schema_version") != 1 or
                manifest.get("review_id") != self.review_id or
                manifest.get("snapshot") != list(self.snapshot) or
                manifest.get("status") != "COMPLETED"):
            raise _unknown("Review manifest is stale or incomplete")
        providers = manifest.get("providers")
        if type(providers) is not list or len(providers) > 32:
            raise _unknown("Invalid provider manifest")
        matches = []
        observed = set()
        for item in providers:
            if type(item) is not dict:
                raise _unknown("Malformed provider record")
            identifier = item.get("id")
            if type(identifier) is not str or not _PROVIDER_ID.fullmatch(identifier) or identifier in observed:
                raise _unknown("Invalid or duplicate provider identity")
            observed.add(identifier)
            if "normalized_file" not in item:
                continue
            if (item.get("exit_code") != 0 or item.get("timed_out") is not False
                    or item.get("truncated") is not False):
                raise _unknown("Incomplete scanner execution")
            if (item.get("stdout_file") != identifier + ".stdout"
                    or item.get("normalized_file") != identifier + ".normalized.json"):
                raise _unknown("Unsafe provider identity")
            for field in ("stdout_sha256", "normalized_sha256"):
                value = item.get(field)
                if type(value) is not str or not _SHA256.fullmatch(value):
                    raise _unknown("Invalid evidence digest")
            _verify_private_digest(review_fd, item["stdout_file"],
                                   item.get("stdout_bytes"), item["stdout_sha256"])
            data = _private_file(review_fd, item["normalized_file"], _MAX_NORMALIZED_BYTES)
            if hashlib.sha256(data).hexdigest() != item["normalized_sha256"]:
                raise _unknown("Normalized evidence digest mismatch")
            report = _json_data(data)
            if (type(report) is not dict or report.get("reviewer_id") != identifier
                    or type(report.get("schema_version")) is not int or report.get("schema_version") != 1 or
                    report.get("verdict") not in {"PASS", "CHANGES_REQUIRED", "ESCALATE"}
                    or report.get("snapshot") != list(self.snapshot)
                    or report.get("raw_stdout_sha256") != item["stdout_sha256"]
                    or type(report.get("findings")) is not list
                    or len(report["findings"]) > 512):
                raise _unknown("Normalized evidence cannot be trusted")
            for finding in report["findings"]:
                if type(finding) is not dict:
                    raise _unknown("Malformed finding")
                if finding.get("id") == finding_id:
                    matches.append((finding, item, item["normalized_sha256"], report["verdict"]))
        if len(matches) != 1:
            raise _unknown("Finding not uniquely available in verified evidence")
        return matches[0]

    def get_review_evidence(self, review_id: str, finding_id: str,
                            context_lines: int = 5) -> tuple[dict, bytes]:
        """Return one verified bounded source excerpt, charging a local request budget."""
        if (type(review_id) is not str or review_id != self.review_id
                or type(finding_id) is not str or not _FINDING_ID.fullmatch(finding_id)
                or type(context_lines) is not int or not 0 <= context_lines <= 20):
            raise _unknown("Invalid or unauthorized evidence request")
        with self._lock:
            return self._retrieve(finding_id, context_lines)

    def _retrieve(self, finding_id: str, context_lines: int) -> tuple[dict, bytes]:
        if self.requests >= self.max_requests:
            raise Abort("REVIEW_EVIDENCE_BUDGET: Request limit exceeded")
        self.requests += 1
        if self.snapshot_reader() != self.snapshot:
            raise _unknown("Current Git snapshot differs from reviewed bytes")
        try:
            root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise _unknown("Repository root is unavailable") from exc
        descriptors = [root_fd]
        try:
            apatch_fd = _directory(root_fd, ".apatch")
            descriptors.append(apatch_fd)
            reviews_fd = _directory(apatch_fd, "reviews", private=True)
            descriptors.append(reviews_fd)
            review_fd = _directory(reviews_fd, self.review_id, private=True)
            descriptors.append(review_fd)
            finding, provider, normalized_hash, scanner_verdict = self._verified_finding(review_fd, finding_id)
            path, line = finding.get("path"), finding.get("line")
            if type(line) is not int or not 1 <= line <= 100000000:
                raise _unknown("Invalid source line")
            excerpt, source_hash = _source_excerpt(root_fd, path, line, context_lines)
            response = {
                "schema_version": 1, "review_id": self.review_id,
                "finding_id": finding_id, "scanner_verdict": scanner_verdict,
                "snapshot_sha256": hashlib.sha256(_encoded(list(self.snapshot))).hexdigest(),
                "provider_id": provider["id"],
                "raw_stdout_sha256": provider["stdout_sha256"],
                "normalized_sha256": normalized_hash,
                "source_sha256": source_hash, "path": path, "line": line,
                "excerpt": excerpt,
            }
            payload = _encoded(response)
            if len(payload) > self.max_response_bytes or (
                    self.bytes_returned + len(payload) > self.max_total_bytes):
                raise Abort("REVIEW_EVIDENCE_BUDGET: Evidence response exceeds byte budget")
            if self.snapshot_reader() != self.snapshot:
                raise _unknown("Git snapshot changed during retrieval")
            self.bytes_returned += len(payload)
            return response, payload
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
