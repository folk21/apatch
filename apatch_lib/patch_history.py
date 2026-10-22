"""External applied-patch name journal with advisory locking and durable append."""

import fcntl
import logging
import os
from contextlib import contextmanager
from pathlib import Path

from .model import Abort, BASENAME_PATTERN


LOGGER = logging.getLogger("apatch.patch_history")


class AppliedPatchHistory:
    def __init__(self, handle):
        self.handle = handle
        self.names = self._load()

    def _load(self):
        self.handle.seek(0)
        raw = self.handle.read()
        if raw and not raw.endswith("\n"):
            raise Abort("Applied patch history ends with an incomplete entry; inspect manually")
        names = set()
        for line in raw.splitlines():
            if not BASENAME_PATTERN.fullmatch(line):
                raise Abort("Applied patch history contains an invalid entry; inspect manually")
            names.add(line)
        return names

    def contains(self, patch_name: str) -> bool:
        return patch_name in self.names

    def append(self, patch_name: str):
        if not BASENAME_PATTERN.fullmatch(patch_name):
            raise Abort("Invalid patch name for applied patch history")
        if patch_name in self.names:
            LOGGER.warning("applied patch already recorded name=%s", patch_name)
            return
        self.handle.seek(0, os.SEEK_END)
        self.handle.write(patch_name + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.names.add(patch_name)
        LOGGER.info("applied patch history appended name=%s", patch_name)


@contextmanager
def locked_history(path: Path):
    """Serialize duplicate checks and journal writes across concurrent invocations."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise Abort(f"History destination must be a regular file: {path}")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with os.fdopen(fd, "r+", encoding="utf-8") as handle:
                fd = -1
                yield AppliedPatchHistory(handle)
        finally:
            if fd >= 0:
                os.close(fd)
    except (OSError, UnicodeError, BlockingIOError) as exc:
        raise Abort(f"Cannot access applied patch history {path}: {exc}") from exc
