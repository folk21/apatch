"""Structural contract for the handoff patch ledger boundary."""

from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import HistoryEntry


@runtime_checkable
class AppliedHistory(Protocol):
    """Writable journal held under the caller's stable advisory lock."""

    @property
    def path(self) -> Path: ...

    def contains(self, patch_name: str) -> bool: ...

    def append(self, patch_name: str, planned_branch: str, real_branch: str,
               *, when: datetime | None = None) -> bool: ...

    def import_entry(self, entry: HistoryEntry) -> bool: ...

    def record_commit_branch(self, patch_name: str, planned_branch: str,
                             real_branch: str) -> bool: ...


@runtime_checkable
class PatchLedgerOperations(Protocol):
    """Verify ordered created patches and atomically manage applied history.

    Callers must hold the context manager throughout read/modify/write work.
    `assert_order` checks predecessors but does not apply any ZIP bytes.
    `persist_registry` preserves the previously recorded prefix under lock.
    """

    def locked(self, path: Path) -> AbstractContextManager[AppliedHistory]: ...

    def assert_order(self, root: Path, patch_name: str, history: AppliedHistory,
                     incoming: tuple[str, ...] | None = None) -> bool: ...

    def persist_registry(self, root: Path,
                         incoming: tuple[str, ...] | None) -> bool: ...
