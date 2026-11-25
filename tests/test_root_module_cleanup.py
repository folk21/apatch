"""Canonical module ownership after removing the remaining root facades."""

import ast
import importlib
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REMOVED = (
    "status", "handoff_selection", "model", "patch", "params_cache", "zip_resume",
    "created_patches", "patch_history", "artifact_packaging", "artifact_preflight",
    "gitutil",
)


class RootModuleCleanupTests(unittest.TestCase):
    def test_root_contains_only_composition_root_and_initializer(self):
        actual = {p.name for p in (ROOT / "apatch_lib").glob("*.py")}
        self.assertEqual(actual, {"__init__.py", "application.py"})
        for old in REMOVED:
            self.assertFalse((ROOT / "apatch_lib" / (old + ".py")).exists())

    def test_canonical_status_and_handoff_selection_imports(self):
        commands = (
            "from apatch_lib.mo_workflows.status import PatchStatus, workflow_key; "
            "from apatch_lib.mo_presentation.status import display_status",
            "from apatch_lib.mo_handoff.selection import HandoffSelection, SelectionKind; "
            "from apatch_lib.mo_handoff.api import Handoff",
            "from apatch_lib.mo_git import repository, commands, inspection; "
            "from apatch_lib.mo_presentation import confirmation",
            "from apatch_lib.mo_handoff_producer import packaging, preflight; "
            "from apatch_lib.mo_handoff_history import journal, registry",
        )
        for statement in commands:
            with self.subTest(statement=statement):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", statement], cwd=ROOT,
                    capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_handoff_selection_import_does_not_initialize_workflow_engine(self):
        script = (
            "import sys; from apatch_lib.mo_handoff.selection import SelectionKind; "
            "assert 'apatch_lib.mo_workflows.sequence' not in sys.modules; "
            "assert 'apatch_lib.mo_workflows.workflow' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=ROOT,
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_internal_python_imports_do_not_depend_on_removed_facades(self):
        from pathlib import PurePath

        removed = {f"apatch_lib.{name}" for name in REMOVED}
        source = [ROOT / "apatch.py", ROOT / "scripts/apatch_pack.py", ROOT / "scripts/apatch_preflight.py"]
        source.extend((ROOT / "apatch_lib").rglob("*.py"))
        for path in source:
            with self.subTest(path=path.relative_to(ROOT)):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        if node.level == 0 and node.module is not None:
                            self.assertNotIn(node.module, removed)
                        elif node.level > 0 and node.module is not None:
                            parts = path.relative_to(ROOT).parts[:-1]
                            base = ".".join(parts[:len(parts) - node.level + 1])
                            self.assertNotIn(base + "." + node.module, removed)
                    elif isinstance(node, ast.Import):
                        for name in node.names:
                            self.assertNotIn(name.name, removed)


if __name__ == "__main__":
    unittest.main()
