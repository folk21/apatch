"""Typed handoff archive port and published implementations.

Callers depend on ArchiveOperations; only the default ZIP service owns the
inspection and extraction mechanics. Stateless metadata helpers remain public.
"""

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..mo_configuration.models import Config
from ..mo_core.contracts import StateDocument
from .constants import BASENAME_PATTERN, BRANCH_PATTERN, DIGEST_PATTERN, SHA_PATTERN
from .models import Archive, Handoff
from .parsing import load_handoff, parse_handoff_payload, safe_relative
from .extraction import apply
from .inspection import handoff_from_zip, inspect, patch_file
from .service import ZipArchiveOperations
from .cache.service import ProjectHandoffCache
from ..mo_handoff_history.api import PatchLedgerOperations
from ..mo_handoff_history.service import ProjectPatchLedger
from ..mo_handoff_producer.models import PackagingResult, PreflightResult, SourceCandidates
from ..mo_handoff_producer.service import VerifiedSourceProducer
from .resume.models import AppliedZipEvidence, APPLIED_PHASES, UNCOMMITTED_PHASES
from .resume.service import ProjectAppliedZipVerifier
from .resume.verification import handoff_signature, verify_applied_zip


@runtime_checkable
class HandoffCacheOperations(Protocol):
    """Read and persist verified cache identities without authorizing workflows."""

    def load(self, root: Path) -> Handoff: ...

    def preflight_write(self, root: Path) -> None: ...

    def save(self, root: Path, handoff: Handoff) -> None: ...


@runtime_checkable
class AppliedZipVerifier(Protocol):
    """Verify applied ZIP evidence without replaying the archive or writing state."""

    def verify(self, root: Path, config: Config, handoff: Handoff,
               state: StateDocument) -> AppliedZipEvidence: ...


@runtime_checkable
class ArchiveOperations(Protocol):
    """ZIP identity verification and application, excluding workflow mutations.

    `inspect` must validate the archive and repository paths without writes.
    `apply` must recheck the inspected identity before replacing source files.
    Callers own Git/workflow admission, history persistence, and recovery.
    """

    def inspect(self, config: Config, handoff: Handoff, root: Path, *,
                before_apply: bool = True) -> Archive: ...

    def apply(self, config: Config, handoff: Handoff, root: Path,
              archive: Archive) -> None: ...

    def handoff_from_zip(self, config: Config, root: Path, name: str) -> Handoff: ...


@runtime_checkable
class ProducerOperations(Protocol):
    """Producer-side verification and ZIP creation without workflow side effects.

    `discover` is read-only. `preflight` may run formatters only when
    explicitly requested. `pack` checks source identity before and after
    writing the ZIP, and never overwrites an existing destination.
    """

    def discover(self, project: Path) -> SourceCandidates: ...

    def preflight(self, project: Path, installation: Path, *,
                  prepare: bool = False) -> PreflightResult: ...

    def pack(self, project: Path, installation: Path, destination: Path, *,
             branch: str, message: str, included: tuple[str, ...],
             deleted: tuple[str, ...] = (), prepare: bool = False,
             base_commit: str | None = None) -> PackagingResult: ...


__all__ = (
    "Archive", "ArchiveOperations", "ZipArchiveOperations", "inspect", "apply",
    "ProducerOperations", "VerifiedSourceProducer",
    "PatchLedgerOperations", "ProjectPatchLedger",
    "HandoffCacheOperations", "ProjectHandoffCache",
    "AppliedZipVerifier", "ProjectAppliedZipVerifier", "AppliedZipEvidence",
    "APPLIED_PHASES", "UNCOMMITTED_PHASES", "handoff_signature", "verify_applied_zip",
    "PreflightResult", "SourceCandidates", "PackagingResult",
    "handoff_from_zip", "patch_file", "Handoff", "load_handoff",
    "parse_handoff_payload", "safe_relative", "BASENAME_PATTERN",
    "BRANCH_PATTERN", "DIGEST_PATTERN", "SHA_PATTERN",
)
