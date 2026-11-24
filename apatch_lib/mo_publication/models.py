"""GitHub PR wire-response types; decoded operations migrate in R4."""

from typing import TypedDict

class GitHubPrIdentity(TypedDict):
    number: int
    state: str
    headRefName: str
    baseRefName: str
    headRefOid: str | None


class GitHubPr(GitHubPrIdentity, total=False):
    url: str
    mergedAt: str | None
    mergeCommit: dict[str, str] | None
    reviewDecision: str | None
    mergeable: str | None
    mergeStateStatus: str | None
    statusCheckRollup: list[dict[str, str | None]] | None


