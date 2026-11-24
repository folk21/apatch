"""Workflow-specific errors for failed verification and safe recovery."""

from ..mo_core.api import Abort


class CheckWorktreeChanged(Abort):
    """Canonical checks changed repository bytes and invalidated verification."""
