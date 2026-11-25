"""R5 runtime workflow ownership, legacy identity and safety boundary tests."""

import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "workflow", "loose", "force", "planner", "sequence", "macros",
    "branch_patch", "branch_reassignment", "action_executor",
    "action_applicability",
)


class WorkflowOwnershipR5Tests(unittest.TestCase):
    def test_single_canonical_implementation_for_each_engine_component(self):
        package = ROOT / "apatch_lib"
        for name in MODULES:
            with self.subTest(name=name):
                self.assertTrue((package / "mo_workflows" / f"{name}.py").is_file())
                self.assertFalse((package / f"{name}.py").exists())
        self.assertTrue((package / "mo_workflows" / "contract.md").is_file())

    def test_legacy_and_canonical_imports_have_identity_in_both_orders(self):
        pairs = [
            (f"apatch_lib.{name}", f"apatch_lib.mo_workflows.{name}")
            for name in MODULES
        ]
        for old_first in (True, False):
            code = (
                "import importlib\n"
                f"pairs = {pairs!r}\n"
                f"for old, new in pairs:\n"
                f"    first, second = (old, new) if {old_first!r} else (new, old)\n"
                "    original = importlib.import_module(first)\n"
                "    alias = importlib.import_module(second)\n"
                "    assert original is alias, (first, second)\n"
                "    assert original.__name__ == new\n"
                "    assert original.__spec__.name == new\n"
            )
            run = subprocess.run(
                [sys.executable, "-B", "-c", code], cwd=ROOT,
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_public_values_remain_independent_of_engine_initialization(self):
        program = (
            "import sys\n"
            "from apatch_lib.mo_workflows.api import ACTION_CODES, WorkflowPhase\n"
            "assert ACTION_CODES[3] == 'APL'\n"
            "assert WorkflowPhase.NEW.value == 'new'\n"
            "assert 'apatch_lib.mo_workflows.workflow' not in sys.modules\n"
            "assert 'apatch_lib.workflow' not in sys.modules\n"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", program], cwd=ROOT,
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_engine_and_mode_classes_are_shared_through_legacy_paths(self):
        from apatch_lib.workflow import Workflow as OldWorkflow
        from apatch_lib.loose import LooseActions as OldLoose
        from apatch_lib.force import ForceActions as OldForce
        from apatch_lib.mo_workflows.workflow import Workflow
        from apatch_lib.mo_workflows.loose import LooseActions
        from apatch_lib.mo_workflows.force import ForceActions
        self.assertIs(Workflow, OldWorkflow)
        self.assertIs(LooseActions, OldLoose)
        self.assertIs(ForceActions, OldForce)
        self.assertTrue(callable(Workflow.interactive))
        self.assertTrue(callable(LooseActions.commit))
        self.assertTrue(callable(ForceActions.merge))

    def test_legacy_mock_seams_patch_canonical_module_globals(self):
        from apatch_lib.mo_workflows import workflow, loose, sequence
        for old_name, new_module, attribute in (
            ("workflow", workflow, "head"),
            ("loose", loose, "worktree_fingerprint"),
            ("sequence", sequence, "ACTION_CODES"),
        ):
            marker = object()
            with patch(f"apatch_lib.{old_name}.{attribute}", marker):
                self.assertIs(getattr(new_module, attribute), marker)

    def test_workflow_module_owner_has_no_unmigrated_relative_imports(self):
        import ast
        for name in MODULES:
            with self.subTest(name=name):
                path = ROOT / "apatch_lib" / "mo_workflows" / (name + ".py")
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.ImportFrom) and node.level == 1:
                        self.assertIn(node.module, (*MODULES, "api"))
