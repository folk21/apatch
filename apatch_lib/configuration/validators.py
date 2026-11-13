"""Pure validation for configuration filenames and branch settings."""

import re
from pathlib import Path

from ..core.api import Abort


def validate_base_branch(value, *, source: str) -> str:
    """Validate a configured Git branch without consulting repository history."""
    if (type(value) is not str or not value or value.strip() != value
            or value.startswith("-") or value == "@" or "@{" in value
            or ".." in value or value.endswith(".") or any(
                ord(char) < 32 or ord(char) == 127 or char in " ~^:?*[\\"
                for char in value)
            or any(not part or part.startswith(".") or part.endswith(".lock")
                   for part in value.split("/"))):
        raise Abort(f"Invalid {source} base_branch: expected a Git branch name")
    return value


def validate_log_subdirectory(value: str) -> Path:
    """Require a relative log directory contained within the project .apatch directory."""
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise Abort("log_directory must be a relative path inside the project .apatch directory")
    directory = Path(value)
    if directory.is_absolute():
        raise Abort("log_directory must be a relative path inside the project .apatch directory")
    return directory


def validate_runtime_filename(value: str) -> Path:
    """Require a single filename for a per-project state or history artifact."""
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value)
            or value in {".", "..", "config.yaml"}):
        raise Abort("state_file and applied_patches_file must be plain filenames inside .apatch")
    return Path(value)

