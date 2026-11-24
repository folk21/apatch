"""Compatibility exports for the handoff-owned applied-patch journal."""

from .mo_handoff_history.journal import (
    LOGGER, MAX_HISTORY_BYTES, AppliedPatchHistory, _check_branch, _parse,
    _serialize, locked_history,
)
from .mo_handoff_history.models import HistoryEntry
