"""Immutable handoff identity and its human-readable subject."""

from dataclasses import dataclass

@dataclass(frozen=True)
class Handoff:
    repository: str
    branch: str
    patch: str
    message: str
    base_commit: str | None
    patch_sha256: str | None
    delete_paths: tuple[str, ...]

    @property
    def subject(self) -> str:
        return self.message.splitlines()[0]


@dataclass(frozen=True)
class Archive:
    """Inspected ZIP identity and declared source changes, never a commit proof."""

    sha256: str
    changed: frozenset[str]
    created_registry: tuple[str, ...] | None = None
    embedded_handoff: Handoff | None = None
