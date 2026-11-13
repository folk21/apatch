"""Persisted workflow shape declarations only; storage and validation live elsewhere."""

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
    session_id: str
    source_branch: str
    reassigned_branch: str



class _OptionalStateFields(TypedDict, total=False):
    feature_sessions: dict[str, dict[str, object]]



class StateDocument(_OptionalStateFields):
    schema_version: int
    workflows: dict[str, WorkflowRecord]
    operation_runs: list[dict[str, object]]

