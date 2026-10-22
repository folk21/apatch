"""Non-destructive migration of legacy tool-local artifacts into a project."""

import logging
from pathlib import Path

from .patch_history import locked_history
from .state import locked_state, save


LOGGER = logging.getLogger("apatch.migration")


def migrate_legacy_artifacts(root: Path, tool_directory: Path, config, state: dict) -> None:
    """Copy matching workflow records and patch history into project-local files."""
    old_state = tool_directory / config.state_path.name
    if not config.state_path.exists() and old_state != config.state_path and old_state.exists():
        with locked_state(old_state) as previous:
            matching = {
                key: record
                for key, record in previous["workflows"].items()
                if isinstance(record, dict) and record.get("repository") == str(root.resolve())
            }
            if matching:
                state["workflows"].update(matching)
                save(config.state_path, state)
                LOGGER.info("imported %d workflow checkpoint(s) from legacy state", len(matching))
                print(f"Imported {len(matching)} workflow checkpoint(s) from legacy state; old file retained.")

    old_history = tool_directory / config.applied_patches_path.name
    if (config.applied_patches_path.exists() or old_history == config.applied_patches_path
            or not old_history.exists()):
        return
    with locked_history(old_history) as previous:
        with locked_history(config.applied_patches_path) as current:
            previous.handle.seek(0)
            imported = 0
            for name in previous.handle.read().splitlines():
                current.append(name)
                imported += 1
            LOGGER.info("imported %d legacy applied-patch history entry/entries", imported)
            if imported:
                print(f"Imported {imported} applied-patch history entry/entries; old file retained.")
