"""Typed read-only boundary for explicit applied ZIP verification."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from ...configuration.models import Config
from ...core.contracts import StateDocument
from ..models import Handoff
from .models import AppliedZipEvidence


@runtime_checkable
class AppliedZipVerifier(Protocol):
    """Prove an existing ZIP was applied, without replaying it.

    A successful result requires matching checkpoint, applied history, APL run,
    archive digest, branch, HEAD and worktree evidence. No writes are allowed.
    """

    def verify(self, root: Path, config: Config, handoff: Handoff,
               state: StateDocument) -> AppliedZipEvidence: ...
