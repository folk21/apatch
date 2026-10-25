"""Atomic, project-local patch history with a stable advisory lock."""

import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .model import Abort, BASENAME_PATTERN
from .storage.locking import exclusive_file_lock


LOGGER = logging.getLogger("apatch.patch_history")
MAX_HISTORY_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class HistoryEntry:
    patch: str
    date: str | None = None
    planned_branch: str | None = None
    real_branch: str | None = None


def _check_branch(value: str) -> None:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise Abort("Applied patch history contains an invalid branch name")


def _parse(raw: str) -> list[HistoryEntry]:
    entries = []
    lines = raw.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line == "---":
            index += 1
            continue
        if BASENAME_PATTERN.fullmatch(line):
            entries.append(HistoryEntry(patch=line))
            index += 1
            continue
        prefixes = ("Date: ", "Patch: ", "Planned feature branch: ", "Real feature branch: ")
        if index + 4 > len(lines):
            raise Abort(f"Applied patch history contains an invalid entry at line {index + 1}: "
                        "expected a complete four-field record; inspect manually")
        for offset, prefix in enumerate(prefixes):
            actual = lines[index + offset]
            if not actual.startswith(prefix):
                field = actual.partition(":")[0][:80]
                raise Abort(
                    f"Applied patch history contains an invalid entry at line {index + offset + 1}: "
                    f"expected '{prefix.rstrip()}', found '{field}'; inspect manually")
        date, patch, planned, real = (
            lines[index + offset][len(prefix):] for offset, prefix in enumerate(prefixes)
        )
        try:
            parsed_date = datetime.fromisoformat(date)
        except ValueError as exc:
            raise Abort("Applied patch history contains an invalid date") from exc
        if parsed_date.tzinfo is None or not BASENAME_PATTERN.fullmatch(patch):
            raise Abort("Applied patch history contains an invalid date or patch name")
        _check_branch(planned)
        _check_branch(real)
        entries.append(HistoryEntry(patch, date, planned, real))
        index += 4
        if index < len(lines) and lines[index] not in {"", "---"}:
            raise Abort("Applied patch history entries must be separated by a blank line or ---")
    return entries


def _serialize(entries: list[HistoryEntry]) -> str:
    blocks = []
    for entry in entries:
        if entry.date is None:
            blocks.append(entry.patch)
        else:
            blocks.append("\n".join((f"Date: {entry.date}", f"Patch: {entry.patch}",
                                     f"Planned feature branch: {entry.planned_branch}",
                                     f"Real feature branch: {entry.real_branch}")))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


class AppliedPatchHistory:
    def __init__(self, path: Path):
        self.path = path
        try:
            if path.exists():
                if path.stat().st_size > MAX_HISTORY_BYTES:
                    raise Abort("Applied patch history exceeds the size limit")
                raw = path.read_text(encoding="utf-8")
            else:
                raw = ""
        except (OSError, UnicodeError) as exc:
            raise Abort(f"Cannot read applied patch history {path}: {exc}") from exc
        self.entries = _parse(raw)
        self.names = {entry.patch for entry in self.entries}

    def contains(self, patch_name: str) -> bool:
        return patch_name in self.names

    def _save(self):
        """Replace the journal atomically while holding its separate, stable lock."""
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise Abort(f"History destination must be a regular file: {self.path}")
        contents = _serialize(self.entries).encode("utf-8")
        if len(contents) > MAX_HISTORY_BYTES:
            raise Abort("Applied patch history exceeds the size limit")
        descriptor, temp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".apatch-history-")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise Abort(f"Cannot update applied patch history {self.path}: {exc}") from exc
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def import_entry(self, entry: HistoryEntry):
        """Preserve original structured or legacy metadata during migration."""
        if entry.patch in self.names:
            return False
        self.entries.append(entry)
        self._save()
        self.names.add(entry.patch)
        return True

    def append(self, patch_name: str, planned_branch: str, real_branch: str,
               *, when: datetime | None = None):
        if not BASENAME_PATTERN.fullmatch(patch_name):
            raise Abort("Invalid patch name for applied patch history")
        _check_branch(planned_branch)
        _check_branch(real_branch)
        if patch_name in self.names:
            LOGGER.warning("applied patch already recorded name=%s", patch_name)
            return False
        instant = when or datetime.now().astimezone()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise Abort("Applied patch timestamp must include a UTC offset")
        timestamp = instant.isoformat(timespec="seconds")
        self.import_entry(HistoryEntry(patch_name, timestamp, planned_branch, real_branch))
        LOGGER.info("applied patch history appended name=%s planned=%s real=%s",
                    patch_name, planned_branch, real_branch)
        return True

    def record_commit_branch(self, patch_name: str, planned_branch: str, real_branch: str):
        """Keep the recorded real branch aligned with a successful Git commit."""
        _check_branch(planned_branch)
        _check_branch(real_branch)
        for index in range(len(self.entries) - 1, -1, -1):
            entry = self.entries[index]
            if entry.patch != patch_name:
                continue
            if entry.date is None:
                self.entries[index] = HistoryEntry(
                    patch_name, datetime.now().astimezone().isoformat(timespec="seconds"),
                    planned_branch, real_branch)
            elif entry.real_branch != real_branch:
                self.entries[index] = replace(entry, real_branch=real_branch)
            else:
                return False
            self._save()
            LOGGER.info("applied patch commit branch recorded name=%s real=%s",
                        patch_name, real_branch)
            return True
        return self.append(patch_name, planned_branch, real_branch)


@contextmanager
def locked_history(path: Path):
    """Use a separate lock inode so atomic journal replacements stay serialized."""
    lock_path = path.with_name(path.name + ".lock")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        for target in (path, lock_path):
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise Abort(f"History destination must be a regular file: {target}")
        with exclusive_file_lock(lock_path, label="applied patch history"):
            yield AppliedPatchHistory(path)
    except (OSError, UnicodeError, BlockingIOError) as exc:
        raise Abort(f"Cannot access applied patch history {path}: {exc}") from exc
