"""Immutable Git evidence models without filesystem or process operations."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorktreeEntry:
    """An exact changed-path snapshot, including Git index and filesystem identity."""

    status: str
    index: tuple[tuple[str, str, str], ...]
    kind: str
    bytes_sha256: str | None = None
    executable: bool | None = None
    symlink_target: str | None = None


@dataclass(frozen=True)
class RepositorySnapshot:
    """Observed Git checkout identity and uncommitted change presence."""

    root: Path
    branch: str
    head: str
    dirty: bool


@dataclass(frozen=True)
class WorktreeSnapshot:
    """Stable changed-path inventory tied to one Git worktree fingerprint."""

    fingerprint: str
    entries: tuple[tuple[str, WorktreeEntry], ...]

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(path for path, _ in self.entries)
