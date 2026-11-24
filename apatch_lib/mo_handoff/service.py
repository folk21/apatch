"""Default ZIP implementation of the handoff archive operations contract."""

from pathlib import Path

from ..mo_configuration.models import Config
from . import extraction, inspection
from .models import Archive, Handoff


class ZipArchiveOperations:
    """Implement archive admission and file writes, without workflow decisions."""

    def inspect(self, config: Config, handoff: Handoff, root: Path, *,
                before_apply: bool = True) -> Archive:
        return inspection.inspect(config, handoff, root, before_apply=before_apply)

    def apply(self, config: Config, handoff: Handoff, root: Path,
              archive: Archive) -> None:
        extraction.apply(config, handoff, root, archive)

    def handoff_from_zip(self, config: Config, root: Path, name: str) -> Handoff:
        return inspection.handoff_from_zip(config, root, name)
