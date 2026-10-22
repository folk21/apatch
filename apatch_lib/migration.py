"""Non-destructive migration of legacy runtime files into the target project."""

import logging
from pathlib import Path

from .local_ignore import ensure_runtime_ignored
from .logging_setup import LOG_FILENAME
from .patch_history import locked_history
from .state import locked_state, save


LOGGER = logging.getLogger("apatch.migration")


def _sources(root: Path, tool_directory: Path, destination: Path, suffix: str):
    """Prefer older project-local files over older tool-local files."""
    candidates = (
        root / ".apatch" / f"{root.name}_{suffix}",
        tool_directory / f"{root.name}_{suffix}",
        tool_directory / destination.name,
    )
    return list(dict.fromkeys(candidate for candidate in candidates
                              if candidate != destination and candidate.is_file()))


def migrate_legacy_artifacts(root: Path, tool_directory: Path, config, state: dict) -> None:
    """Import legacy project-specific names without modifying their originals."""
    old_project_state = root / ".apatch" / f"{root.name}_apply_patch.state.json"
    old_project_history = root / ".apatch" / f"{root.name}_applied_patches.txt"
    if old_project_state.is_file() or old_project_history.is_file():
        ensure_runtime_ignored(root, config.log_directory, LOG_FILENAME,
                               old_project_state, old_project_history)
    if not config.state_path.exists():
        for source in _sources(root, tool_directory, config.state_path,
                               "apply_patch.state.json"):
            with locked_state(source) as previous:
                matching = {
                    key: record for key, record in previous["workflows"].items()
                    if isinstance(record, dict) and record.get("repository") == str(root.resolve())
                }
            if matching:
                state["workflows"].update(matching)
                save(config.state_path, state)
                LOGGER.info("imported %d checkpoint(s) from %s", len(matching), source)
                print(f"Imported {len(matching)} workflow checkpoint(s) from legacy state; old file retained.")
                break

    if config.applied_patches_path.exists():
        return
    for source in _sources(root, tool_directory, config.applied_patches_path,
                           "applied_patches.txt"):
        with locked_history(source) as previous:
            entries = previous.entries
        if not entries:
            continue
        with locked_history(config.applied_patches_path) as current:
            imported = sum(bool(current.import_entry(entry)) for entry in entries)
        if imported:
            LOGGER.info("imported %d applied patch history entries from %s", imported, source)
            print(f"Imported {imported} applied-patch history entry/entries; old file retained.")
        break
