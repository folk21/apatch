"""Immutable effective configuration; file access belongs to loaders."""

from dataclasses import dataclass
from pathlib import Path

from ..review.api import ReviewProvider


@dataclass(frozen=True)
class Config:
    downloads: Path
    state_path: Path
    log_directory: Path
    applied_patches_path: Path
    remote: str
    base: str
    checks: tuple[tuple[str, ...], ...]
    require_approval: bool
    require_checks: bool
    merge_method: str
    max_bytes: int
    require_patch_feature_branch: bool = False
    github_timeout_seconds: int = 30
    review_approval_source: str = "global"
    required_checks_source: str = "global"
    check_timeout_seconds: int = 900
    check_idle_timeout_seconds: int = 30
    progress_global_limit: int = 8
    progress_project_limit: int = 3
    base_branch_source: str = "global"
    prepare_checks: tuple[tuple[str, ...], ...] = ()
    check_worktree_policy: str = "stop"
    format_commands: tuple[tuple[str, ...], ...] = ()
    github_ci_wait_seconds: int = 300
    reviewers: tuple["ReviewProvider", ...] = ()
    review_required: bool = False
    review_timeout_seconds: int = 180
    review_max_bytes: int = 131072
    review_artifacts_enabled: bool = False
    review_artifact_max_bytes: int = 8388608
    review_context_max_bytes: int = 32768
    review_context_external_consent: bool = False
    review_context_include_messages: bool = False
    review_context_include_diff: bool = False
    review_retention_enabled: bool = False
    review_retention_max_runs: int = 100
    review_retention_max_bytes: int = 536870912
    review_retention_max_age_days: int = 30

