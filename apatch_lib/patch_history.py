"""Compatibility exports for the handoff-owned applied-patch journal."""

from .handoff.history.journal import (
    LOGGER, MAX_HISTORY_BYTES, AppliedPatchHistory, _check_branch, _parse,
    _serialize, locked_history,
)
from .handoff.history.models import HistoryEntry
