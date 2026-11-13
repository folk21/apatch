"""Versioned handoff protocol identifiers and validation expressions."""

import re

BRANCH_PATTERN = re.compile(r"^feature/[A-Za-z0-9][A-Za-z0-9._/-]*$")
BASENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.zip$")
SHA_PATTERN = re.compile(r"^[a-f0-9]{40}$")
DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")


HANDOFF_FIELDS = frozenset({
    "schema_version", "repository", "feature_branch", "patch_file",
    "commit_message", "base_commit", "patch_sha256", "delete_paths",
})
MAX_COMMIT_MESSAGE_LENGTH = 8192
