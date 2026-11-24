"""Immutable facts and unchanged checkpoint phase categories for applied ZIP resumes."""

from dataclasses import dataclass


APPLIED_PHASES = frozenset({
    "patch_applied", "verified", "committed", "pushed", "pr_created", "merged", "synced",
})
UNCOMMITTED_PHASES = frozenset({"patch_applied", "verified"})


@dataclass(frozen=True)
class AppliedZipEvidence:
    patch: str
    phase: str
    branch: str
    pending_branch: bool
