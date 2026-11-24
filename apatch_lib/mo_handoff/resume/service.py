"""Default applied ZIP verifier with an injectable read-only implementation."""

from collections.abc import Callable
from pathlib import Path

from ...mo_configuration.models import Config
from ...mo_core.contracts import StateDocument
from ..models import Handoff
from .models import AppliedZipEvidence
from .verification import verify_applied_zip


class ProjectAppliedZipVerifier:
    """Consume the unchanged source-verification algorithm behind a typed port."""

    def __init__(self, verify_fn: Callable[[Path, Config, Handoff, StateDocument],
                                        AppliedZipEvidence] = verify_applied_zip):
        self._verify = verify_fn

    def verify(self, root: Path, config: Config, handoff: Handoff,
               state: StateDocument) -> AppliedZipEvidence:
        return self._verify(root, config, handoff, state)
