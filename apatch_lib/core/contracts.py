"""Typed views of persisted workflow data and GitHub PR responses.

The JSON boundaries validate these fields before exposing mutable dictionaries
to existing workflow consumers. Unknown persistence extensions are retained.
"""

from dataclasses import dataclass
from typing import TypedDict

from .enums import OperationOutcome
from ..model import RemoteOutcomeUnknown


class WorkflowRecord(TypedDict, total=False):
    repository: str
    branch: str
    patch_file: str
    handoff_signature: str
    phase: str
    applied_branch: str
    branch_origin: str
    branch_base: str
    extracted_on_branch: str
    archive_sha256: str
    before_patch_head: str
    remote_before_patch_head: str | None
    remote_url: str
    changed_paths: list[str]
    zip_first: bool
    loose_backup: str | None
    verified_fingerprint: str
    verified_head: str
    verified_commit: str
    verified_branch: str
    commit_sha: str
    pushed_sha: str
    pr_number: int
    local_base_head: str
    merge_commit_sha: str
    continued_by: str
    continued_patch: str
    superseded_by: str
    session_id: str


class _OptionalStateFields(TypedDict, total=False):
    feature_sessions: dict[str, dict[str, object]]


class StateDocument(_OptionalStateFields):
    schema_version: int
    workflows: dict[str, WorkflowRecord]
    operation_runs: list[dict[str, object]]


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


@dataclass(frozen=True)
class ActionResult:
    """An action's verified completion, independent of incidental Git changes."""

    outcome: OperationOutcome
    evidence: str | None = None
    confirmed_partial_effect: bool = False

    @classmethod
    def succeeded(cls, evidence: str) -> "ActionResult":
        return cls(OperationOutcome.SUCCESS, evidence)

    @classmethod
    def already_satisfied(cls, evidence: str) -> "ActionResult":
        return cls(OperationOutcome.ALREADY_SATISFIED, evidence)

    @classmethod
    def partial(cls, evidence: str) -> "ActionResult":
        """Describe a verified local effect without claiming action completion."""
        return cls(OperationOutcome.NO_OP, evidence, confirmed_partial_effect=True)

    @classmethod
    def completed(cls, value: object, *, declined: bool) -> "ActionResult":
        """Normalize explicit action returns; never infer success from Git deltas."""
        if declined:
            return cls(OperationOutcome.CANCELLED)
        if isinstance(value, cls):
            return value
        if value is True:
            return cls.succeeded("Action returned verified success")
        if value is False or value is None:
            return cls(OperationOutcome.NO_OP)
        raise TypeError(f"Unsupported action return type: {type(value).__name__}")

    @classmethod
    def failed(cls, error: BaseException, *, declined: bool) -> "ActionResult":
        """Give uncertain remote effects priority over local confirmation state."""
        if isinstance(error, RemoteOutcomeUnknown):
            return cls(OperationOutcome.UNKNOWN_REMOTE_RESULT)
        if declined:
            return cls(OperationOutcome.CANCELLED)
        return cls(OperationOutcome.ERROR)

    @property
    def progress_outcome(self) -> str:
        """Preserve existing progress storage's NO_OP spelling."""
        if self.outcome == OperationOutcome.ALREADY_SATISFIED:
            return OperationOutcome.NO_OP.value
        if self.outcome == OperationOutcome.ERROR:
            return "FAILED"
        return self.outcome.value
