"""Compatibility wrappers for producer packaging and historical mock seams."""

from pathlib import Path

from .mo_handoff_producer.models import PackagingResult, PreflightResult, SourceCandidates
from .mo_handoff_producer.packaging import (MAX_SOURCE_PATHS, _read_source_file,
                                        discover_source_paths, pack_source as _pack_source)
from .mo_handoff_producer.preflight import preflight


def pack_source(project: Path, installation: Path, destination: Path, *,
                branch: str, message: str, included: tuple[str, ...],
                deleted: tuple[str, ...] = (), prepare: bool = False,
                base_commit: str | None = None) -> PackagingResult:
    """Preserve previous patch targets during the producer package migration."""
    return _pack_source(
        project, installation, destination, branch=branch, message=message,
        included=included, deleted=deleted, prepare=prepare,
        base_commit=base_commit, preflight_fn=preflight,
        read_source_file_fn=_read_source_file)


__all__ = ("PackagingResult", "PreflightResult", "SourceCandidates",
           "discover_source_paths", "pack_source", "MAX_SOURCE_PATHS", "preflight")
