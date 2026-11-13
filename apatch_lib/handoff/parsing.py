"""Validate untrusted handoff metadata and read legacy JSON handoffs."""

import json
import re
from pathlib import Path

from ..core.api import Abort
from .constants import (BASENAME_PATTERN, BRANCH_PATTERN, DIGEST_PATTERN,
                        HANDOFF_FIELDS, MAX_COMMIT_MESSAGE_LENGTH, SHA_PATTERN)
from .models import Handoff


def safe_relative(path: str) -> str:
    if (not isinstance(path, str) or not path or "\\" in path or "\x00" in path
            or path.startswith("/") or any(p in {"", ".", ".."} for p in path.split("/"))
            or any(p == ".git" for p in path.split("/"))):
        raise Abort(f"Unsafe path: {path!r}")
    return path


def load_handoff(path: Path) -> Handoff:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Abort(f"Cannot read handoff JSON: {exc}") from exc

    return parse_handoff_payload(payload)


def parse_handoff_payload(payload, *, embedded=False) -> Handoff:
    """Validate identical handoff fields from external JSON or reserved ZIP metadata."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise Abort("Unsupported handoff schema_version")
    expected = HANDOFF_FIELDS
    if set(payload) - expected:
        raise Abort(f"Unknown handoff keys: {sorted(set(payload) - expected)}")
    if embedded and "patch_sha256" in payload:
        raise Abort("Embedded ZIP parameters must not contain the ZIP's own patch_sha256")
    repo, branch = payload.get("repository"), payload.get("feature_branch")
    patch, msg = payload.get("patch_file"), payload.get("commit_message")
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", repo):
        raise Abort("Invalid repository")
    if not isinstance(branch, str) or not BRANCH_PATTERN.fullmatch(branch) or ".." in branch or branch.endswith("/"):
        raise Abort("Invalid feature_branch")
    if not isinstance(patch, str) or not BASENAME_PATTERN.fullmatch(patch):
        raise Abort("patch_file must be an ASCII-safe ZIP basename, without a directory")
    if not isinstance(msg, str) or not msg.strip() or len(msg) > MAX_COMMIT_MESSAGE_LENGTH:
        raise Abort("commit_message is missing or too long")
    if not msg.splitlines()[0].strip() or "\x00" in msg:
        raise Abort("Invalid commit_message")
    base = payload.get("base_commit")
    digest = payload.get("patch_sha256")
    if base is not None and (not isinstance(base, str) or not SHA_PATTERN.fullmatch(base)):
        raise Abort("base_commit must be a full lowercase Git SHA")
    if digest is not None and (not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest)):
        raise Abort("patch_sha256 must be a lowercase SHA-256")
    paths = payload.get("delete_paths", [])
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise Abort("delete_paths must be a list of repository-relative paths")
    return Handoff(repo, branch, patch, msg.rstrip() + "\n", base, digest,
                   tuple(safe_relative(p) for p in paths))
