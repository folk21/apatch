"""Canonical mo_* package naming and identity-preserving legacy imports."""

import ast
import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "cli", "configuration", "core", "feature_sessions", "git", "handoff", "presentation",
    "publication", "review", "storage", "workflows", "audit", "verification",
)
HANDOFF_PEERS = ("history", "producer")
HANDOFF_INTERNAL = ("cache", "resume")
EXPECTED_INTERNAL_PACKAGES = {
    "mo_handoff": list(HANDOFF_INTERNAL),
    "mo_cli": ["resources"],
}
IMPORT_PAIRS = (
    ("configuration.api", "mo_configuration.api"),
    ("core.api", "mo_core.api"),
    ("git.api", "mo_git.api"),
    ("handoff.api", "mo_handoff.api"),
    ("handoff.cache.api", "mo_handoff.api"),
    ("handoff.cache.service", "mo_handoff.cache.service"),
    ("mo_handoff_cache.api", "mo_handoff.api"),
    ("mo_handoff_cache.service", "mo_handoff.cache.service"),
    ("handoff.history.journal", "mo_handoff_history.journal"),
    ("handoff.producer.packaging", "mo_handoff_producer.packaging"),
    ("handoff.resume.api", "mo_handoff.api"),
    ("handoff.resume.verification", "mo_handoff.resume.verification"),
    ("mo_handoff_resume.api", "mo_handoff.api"),
    ("mo_handoff_resume.verification", "mo_handoff.resume.verification"),
    ("presentation.execution", "mo_presentation.execution"),
    ("publication.api", "mo_publication.api"),
    ("review.api", "mo_review.api"),
    ("storage.locking", "mo_storage.locking"),
    ("workflows.api", "mo_workflows.api"),
)


def _legacy_implementation_files(directory: Path) -> list[str]:
    """Ignore abandoned cache directories, but reject old importable source."""
    if not directory.is_dir():
        return []
    return sorted(
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and (
            path.name == "contract.md"
            or path.suffix in {".py", ".pyi", ".so", ".pyd"}
            or (path.suffix == ".pyc" and "__pycache__" not in path.parts)
        )
    )


class ModulePrefixTests(unittest.TestCase):
    def test_domain_packages_have_only_canonical_prefixed_directories(self):
        package_root = ROOT / "apatch_lib"
        for package in PACKAGES:
            with self.subTest(package=package):
                self.assertTrue((package_root / f"mo_{package}" / "__init__.py").is_file())
                legacy = package_root / package
                self.assertFalse(legacy.is_symlink())
                if legacy.exists():
                    self.assertTrue(legacy.is_dir())
                    self.assertEqual([], _legacy_implementation_files(legacy), legacy)
        for package in HANDOFF_PEERS:
            with self.subTest(component=package):
                self.assertTrue((package_root / f"mo_handoff_{package}" / "__init__.py").is_file())
        for component in HANDOFF_INTERNAL:
            internal = package_root / "mo_handoff" / component
            with self.subTest(internal=component):
                self.assertTrue((internal / "__init__.py").is_file())
                self.assertFalse((internal / "api.py").exists())
                self.assertFalse((internal / "contract.md").exists())
                legacy = package_root / f"mo_handoff_{component}"
                self.assertEqual([], _legacy_implementation_files(legacy), legacy)
        for package in package_root.iterdir():
            if package.is_dir() and package.name.startswith("mo_"):
                nested = sorted(
                    child.name for child in package.iterdir()
                    if child.is_dir() and (child / "__init__.py").exists()
                )
                self.assertEqual(
                    EXPECTED_INTERNAL_PACKAGES.get(package.name, []),
                    nested, f"Unexpected internal packages in {package}",
                )
                if package.name == "mo_cli":
                    resource_sources = sorted(
                        path.name for path in (package / "resources").iterdir()
                        if path.suffix in {".py", ".pyi"}
                    )
                    self.assertEqual(["__init__.py"], resource_sources)

    def test_cache_and_resume_own_no_separate_module_contract(self):
        from apatch_lib.mo_handoff import api
        from apatch_lib.mo_handoff.cache import service as cache_service
        from apatch_lib.mo_handoff.resume import service as resume_service
        self.assertIs(api.ProjectHandoffCache, cache_service.ProjectHandoffCache)
        self.assertIs(api.ProjectAppliedZipVerifier, resume_service.ProjectAppliedZipVerifier)
        self.assertTrue(hasattr(api, "HandoffCacheOperations"))
        self.assertTrue(hasattr(api, "AppliedZipVerifier"))

    def test_old_package_cache_residue_is_not_a_legacy_implementation(self):
        with TemporaryDirectory() as temporary:
            legacy = Path(temporary) / "handoff"
            cache = legacy / "history" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "journal.cpython-313.pyc").write_bytes(b"cache")
            (legacy / ".DS_Store").write_bytes(b"finder")
            self.assertEqual([], _legacy_implementation_files(legacy))

            source = legacy / "history" / "journal.py"
            source.write_text("# Legacy source must not remain\n", encoding="utf-8")
            self.assertEqual(["history/journal.py"], _legacy_implementation_files(legacy))
            source.unlink()
            contract = legacy / "contract.md"
            contract.write_text("# Legacy contract\n", encoding="utf-8")
            self.assertEqual(["contract.md"], _legacy_implementation_files(legacy))

    def test_legacy_and_canonical_imports_are_identical_in_both_orders(self):
        for old_first in (True, False):
            script = """
import importlib
pairs = __PAIRS__
for old, new in pairs:
    old_name, new_name = 'apatch_lib.' + old, 'apatch_lib.' + new
    first, second = (old_name, new_name) if __OLD_FIRST__ else (new_name, old_name)
    a = importlib.import_module(first)
    b = importlib.import_module(second)
    assert a is b, (first, second)
    assert a.__name__ == new_name, (a.__name__, new_name)
    assert a.__spec__.name == new_name, (a.__spec__.name, new_name)
assert importlib.import_module('apatch_lib.core.api').Abort is importlib.import_module('apatch_lib.mo_core.api').Abort
""".replace("__PAIRS__", repr(IMPORT_PAIRS)).replace(
                "__OLD_FIRST__", repr(old_first)
            )
            result = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=ROOT,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_canonical_owners_have_no_legacy_package_imports(self):
        for file in (ROOT / "apatch_lib").rglob("*.py"):
            source = file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports = [node.module]
                else:
                    continue
                for name in imports:
                    self.assertFalse(
                        any(name == f"apatch_lib.{old}" or
                            name.startswith(f"apatch_lib.{old}.")
                            for old in PACKAGES),
                        (file, name),
                    )


if __name__ == "__main__":
    unittest.main()
