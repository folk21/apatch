"""Compatibility facade for the Git adapter and user confirmation helpers."""

from .mo_git.commands import (
    LOGGER, REDACT_FLAGS, FAILURE_TAIL_LINES, FAILURE_TAIL_LINE_CHARS,
    CHECK_SUMMARY_LINES, CHECK_SUMMARY_CHARS, ANSI_ESCAPE,
    COMMAND_DESCRIPTIONS, command_description, display_command,
    _check_failure_summary, _run_captured_with_deadline, run,
)
from .mo_git.repository import (
    output, repository_root, current_branch, head, is_clean, require_clean,
    require_branch, branch_exists, remote_head, status_paths, worktree_fingerprint,
)
from .mo_presentation.confirmation import (
    _SKIP_APPROVALS, _CONFIRMATION_DECLINED, set_skip_approvals,
    reset_skip_approvals, skip_approvals_enabled, confirm,
    clear_confirmation_declined, confirmation_was_declined,
)
from .mo_git.models import WorktreeEntry
from .mo_git.inspection import worktree_inventory, worktree_change_details
