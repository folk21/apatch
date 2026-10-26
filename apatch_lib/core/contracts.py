"""Typed views of persisted workflow data and GitHub PR responses.

The JSON boundaries validate these fields before exposing mutable dictionaries
to existing workflow consumers. Unknown persistence extensions are retained.
"""

from typing import TypedDict


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


class StateDocument(TypedDict):
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
    reviewDecision: str | None
    mergeable: str | None
    mergeStateStatus: str | None
    statusCheckRollup: list[dict[str, str | None]] | None
