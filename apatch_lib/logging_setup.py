"""Configure an append-only audit log with a validated patch identity."""

import logging
import os
from pathlib import Path

from .model import Abort


LOG_FILENAME = "signalharvester_apply_patch.log"
LOGGER_NAME = "apatch"


class PatchContextFilter(logging.Filter):
    """Attach handoff identity to every record, including subprocess records."""

    def __init__(self):
        super().__init__()
        self.patch = "unavailable"
        self.branch = "unavailable"
        self.repository = "unavailable"

    def filter(self, record):
        record.patch = self.patch
        record.branch = self.branch
        record.repository = self.repository
        return True


_CONTEXT = PatchContextFilter()


def set_context(*, patch: str, branch: str, repository: str):
    _CONTEXT.patch = patch
    _CONTEXT.branch = branch
    _CONTEXT.repository = repository


def configure(log_directory: Path) -> Path:
    """Install exactly one private file handler with patch-aware formatting."""
    path = log_directory / LOG_FILENAME
    try:
        log_directory.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise Abort(f"Log destination must be a regular file: {path}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        os.close(descriptor)
        path.chmod(0o600)
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as exc:
        raise Abort(f"Cannot initialize log file {path}: {exc}") from exc
    handler.addFilter(_CONTEXT)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s level=%(levelname)s patch=%(patch)s branch=%(branch)s "
        "repository=%(repository)s logger=%(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    ))
    logger = logging.getLogger(LOGGER_NAME)
    for previous in list(logger.handlers):
        logger.removeHandler(previous)
        previous.close()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    return path
