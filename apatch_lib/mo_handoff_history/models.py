"""Immutable history record shared by the persistent journal and its consumers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryEntry:
    patch: str
    date: str | None = None
    planned_branch: str | None = None
    real_branch: str | None = None
