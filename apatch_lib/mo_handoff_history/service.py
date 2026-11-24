"""Default local patch-ledger implementation behind the handoff protocol."""

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Callable

from .api import AppliedHistory
from .journal import locked_history
from .registry import assert_patch_order, persist_registry


class ProjectPatchLedger:
    """Keep journal locking and ordered-registry persistence in their owners."""

    def __init__(
        self, *,
        lock: Callable[[Path], AbstractContextManager[AppliedHistory]] = locked_history,
        order: Callable[..., bool] = assert_patch_order,
        persist: Callable[..., bool] = persist_registry,
    ) -> None:
        self._lock = lock
        self._order = order
        self._persist = persist

    def locked(self, path: Path) -> AbstractContextManager[AppliedHistory]:
        return self._lock(path)

    def assert_order(self, root: Path, patch_name: str, history: AppliedHistory,
                     incoming: tuple[str, ...] | None = None) -> bool:
        return self._order(root, patch_name, history, incoming)

    def persist_registry(self, root: Path,
                         incoming: tuple[str, ...] | None) -> bool:
        return self._persist(root, incoming)
