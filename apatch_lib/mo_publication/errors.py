"""Uncertain external publication results must never be retried blindly."""

from ..mo_core.api import Abort


class RemoteOutcomeUnknown(Abort):
    """A remote mutation may have happened despite its failed acknowledgment."""
