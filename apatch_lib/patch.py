"""Compatibility aliases for handoff ZIP inspection and extraction.

New domain consumers should import from `handoff.api`, not this module.
"""

from .core.paths import PARAMS_MEMBER, REGISTRY_MEMBER
from .handoff.api import (Archive, apply, handoff_from_zip, inspect, patch_file)

__all__ = (
    "Archive", "apply", "handoff_from_zip", "inspect", "patch_file",
    "PARAMS_MEMBER", "REGISTRY_MEMBER",
)
