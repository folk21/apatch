"""Concrete source producer behind the handoff producer Protocol."""

from pathlib import Path

from .models import PackagingResult, PreflightResult, SourceCandidates
from .packaging import discover_source_paths, pack_source
from .preflight import preflight


class VerifiedSourceProducer:
    """Verify Git source identity and create a single safe ZIP without branch writes."""

    def discover(self, project: Path) -> SourceCandidates:
        return discover_source_paths(project)

    def preflight(self, project: Path, installation: Path, *,
                  prepare: bool = False) -> PreflightResult:
        return preflight(project, installation, prepare=prepare)

    def pack(self, project: Path, installation: Path, destination: Path, *,
             branch: str, message: str, included: tuple[str, ...],
             deleted: tuple[str, ...] = (), prepare: bool = False,
             base_commit: str | None = None) -> PackagingResult:
        return pack_source(project, installation, destination, branch=branch,
                           message=message, included=included, deleted=deleted,
                           prepare=prepare, base_commit=base_commit)
