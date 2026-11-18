"""Typed contract for verified project-local handoff cache operations."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import Handoff


@runtime_checkable
class HandoffCacheOperations(Protocol):
    """Read verified handoffs and safely persist selected ZIP identities.

    Loading is read-only. Preflight rejects unsafe targets before extraction.
    Saving requires an already verified ZIP digest; the cache is not a
    workflow checkpoint and does not authorize applying or publishing a ZIP.
    """

    def load(self, root: Path) -> Handoff: ...

    def preflight_write(self, root: Path) -> None: ...

    def save(self, root: Path, handoff: Handoff) -> None: ...
