"""apatch CLI implementation and legacy module import compatibility."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from types import ModuleType


# Legacy names map to the canonical prefixed packages without duplicate classes.
_LEGACY_PACKAGES = {
    "configuration": "mo_configuration",
    "core": "mo_core",
    "git": "mo_git",
    "handoff": "mo_handoff",
    "presentation": "mo_presentation",
    "publication": "mo_publication",
    "review": "mo_review",
    "storage": "mo_storage",
    "workflows": "mo_workflows",
    "mo_handoff_cache": "mo_handoff.cache",
    "mo_handoff_resume": "mo_handoff.resume",
}
_HANDOFF_PACKAGES = {
    "cache": "mo_handoff.cache",
    "history": "mo_handoff_history",
    "producer": "mo_handoff_producer",
    "resume": "mo_handoff.resume",
}


def _canonical_module(fullname: str) -> str | None:
    """Resolve only known legacy package prefixes, not unrelated module names."""
    prefix = f"{__name__}."
    if not fullname.startswith(prefix):
        return None
    parts = fullname[len(prefix):].split(".")
    mapped = _LEGACY_PACKAGES.get(parts[0])
    if mapped is None:
        return None
    parts[0] = mapped
    if mapped == "mo_handoff" and len(parts) > 1 and parts[1] in _HANDOFF_PACKAGES:
        mapped = _HANDOFF_PACKAGES[parts[1]]
        parts = [mapped, *parts[2:]]
    canonical = ".".join(parts)
    if canonical in {"mo_handoff.cache.api", "mo_handoff.resume.api"}:
        canonical = "mo_handoff.api"
    return prefix + canonical


class _LegacyModuleLoader(importlib.abc.Loader):
    """Return the existing canonical module object for historical import paths."""

    def __init__(self, canonical: str) -> None:
        self.canonical = canonical
        self._module_spec = None
        self._package = None
        self._path = None

    def create_module(self, spec: object) -> ModuleType:
        module = importlib.import_module(self.canonical)
        self._module_spec = module.__spec__
        self._package = module.__package__
        self._path = getattr(module, "__path__", None)
        return module

    def exec_module(self, module: ModuleType) -> None:
        # Importlib initializes the alias spec on the returned module object.
        # Restore canonical metadata to keep relative imports and reload stable.
        module.__spec__ = self._module_spec
        module.__package__ = self._package
        if self._path is not None:
            module.__path__ = self._path


class _LegacyModuleFinder(importlib.abc.MetaPathFinder):
    """Recognize deprecated internal package names without shadow directories."""

    def find_spec(self, fullname: str, path: object = None, target: object = None):
        canonical = _canonical_module(fullname)
        if canonical is None:
            return None
        canonical_spec = importlib.util.find_spec(canonical)
        if canonical_spec is None:
            return None
        return importlib.util.spec_from_loader(
            fullname,
            _LegacyModuleLoader(canonical),
            is_package=canonical_spec.submodule_search_locations is not None,
        )


# Install once; imports using mo_* paths are unaffected by the finder.
if not any(isinstance(item, _LegacyModuleFinder) for item in sys.meta_path):
    sys.meta_path.insert(0, _LegacyModuleFinder())
