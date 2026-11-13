"""R2.3 workflow contract extraction without import or behavioral drift."""

import ast
import dataclasses
import subprocess
import sys
import unittest
from pathlib import Path

from apatch_lib import model
from apatch_lib.core import actions as old_actions
from apatch_lib.core import contracts as old_contracts
from apatch_lib.core import enums as old_enums
from apatch_lib.core.api import Abort
from apatch_lib.publication.api import RemoteOutcomeUnknown
from apatch_lib.workflows import api as domain
from apatch_lib.workflows import actions, enums, models, results


class WorkflowDomainBoundaryTests(unittest.TestCase):
    def test_legacy_imports_are_same_objects_as_owning_api(self) -> None:
        pairs = (
            (old_actions.ACTION_CODES, domain.ACTION_CODES),
            (old_actions.action_number, domain.action_number),
            (old_enums.WorkflowPhase, domain.WorkflowPhase),
            (old_enums.OperationOutcome, domain.OperationOutcome),
            (old_enums.PHASE_VALUES, domain.PHASE_VALUES),
            (old_contracts.WorkflowRecord, domain.WorkflowRecord),
            (old_contracts.StateDocument, domain.StateDocument),
            (old_contracts.ActionResult, domain.ActionResult),
            (model.CheckWorktreeChanged, domain.CheckWorktreeChanged),
        )
        for legacy, public in pairs:
            with self.subTest(value=public):
                self.assertIs(legacy, public)

    def test_owning_source_modules_are_canonical(self) -> None:
        self.assertEqual(domain.WorkflowPhase.__module__, enums.__name__)
        self.assertEqual(domain.OperationOutcome.__module__, enums.__name__)
        self.assertEqual(domain.ActionResult.__module__, results.__name__)
        self.assertEqual(domain.WorkflowRecord.__module__, models.__name__)
        self.assertEqual(domain.StateDocument.__module__, models.__name__)
        self.assertEqual(domain.CheckWorktreeChanged.__module__,
                         "apatch_lib.workflows.errors")
        self.assertTrue(dataclasses.is_dataclass(domain.ActionResult))
        self.assertTrue(domain.ActionResult.__dataclass_params__.frozen)

    def test_state_models_only_declare_shapes(self) -> None:
        tree = ast.parse(Path(models.__file__).read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                             for node in tree.body))
        imported = {alias.name for node in tree.body
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names}
        self.assertEqual(imported, {"TypedDict"})
        self.assertEqual(set(domain.StateDocument.__annotations__),
                         {"schema_version", "workflows", "operation_runs",
                          "feature_sessions"})
        self.assertIn("reassigned_branch", domain.WorkflowRecord.__annotations__)
        self.assertIn("before_patch_head", domain.WorkflowRecord.__annotations__)

    def test_legacy_core_contains_no_domain_class_implementations(self) -> None:
        for component in (old_actions, old_enums, old_contracts):
            with self.subTest(component=component.__name__):
                tree = ast.parse(Path(component.__file__).read_text(encoding="utf-8"))
                self.assertFalse(any(isinstance(node, (ast.ClassDef, ast.FunctionDef))
                                     for node in tree.body))

    def test_action_numbers_remain_stable(self) -> None:
        codes = ("EXT", "BRN", "BAP", "APL", "CHK", "CMT", "PSH", "PR",
                 "MRG", "SYN", "STS", "AUD", "FMT", "REV")
        self.assertEqual(actions.ACTION_CODES, codes)
        self.assertEqual(tuple(domain.action_number(code) for code in codes),
                         tuple(range(len(codes))))
        self.assertEqual(domain.action_number("3"), 3)
        with self.assertRaises(ValueError):
            domain.action_number("14")

    def test_phase_identifiers_and_effects_are_unchanged(self) -> None:
        self.assertEqual(domain.PHASE_VALUES,
                         frozenset(item.value for item in domain.WorkflowPhase))
        self.assertIn("patch_applied", domain.PHASE_VALUES)
        self.assertEqual(domain.ActionResult.partial("pending").progress_outcome,
                         "NO_OP")
        self.assertEqual(domain.ActionResult.already_satisfied("verified").progress_outcome,
                         "NO_OP")
        self.assertEqual(domain.ActionResult.completed(True, declined=True).outcome,
                         domain.OperationOutcome.CANCELLED)
        with self.assertRaises(TypeError):
            domain.ActionResult.completed({"unexpected": "evidence"}, declined=False)

    def test_unknown_publication_effect_is_never_downgraded_to_cancelled(self) -> None:
        result = domain.ActionResult.failed(RemoteOutcomeUnknown("unknown"),
                                            declined=True)
        self.assertEqual(result.outcome, domain.OperationOutcome.UNKNOWN_REMOTE_RESULT)
        self.assertEqual(result.progress_outcome, "UNKNOWN_REMOTE_RESULT")

    def test_verification_error_has_stable_identity_and_base(self) -> None:
        self.assertTrue(issubclass(domain.CheckWorktreeChanged, Abort))
        with self.assertRaises(model.Abort):
            raise domain.CheckWorktreeChanged("modified by check")

    def test_public_domain_import_does_not_import_workflow_engine(self) -> None:
        script = ("import sys; from apatch_lib.workflows import api; "
                  "assert 'apatch_lib.workflow' not in sys.modules; "
                  "assert 'apatch_lib.state' not in sys.modules")
        proc = subprocess.run([sys.executable, "-B", "-c", script],
                              cwd=Path(__file__).resolve().parents[1],
                              text=True, capture_output=True, timeout=15, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_workflows_public_contract_files_exist(self) -> None:
        package = Path(domain.__file__).resolve().parent
        self.assertTrue((package / "contract.md").is_file())
        exported = set(domain.__all__)
        for name in ("ActionResult", "WorkflowPhase", "OperationOutcome",
                     "StateDocument", "WorkflowRecord", "CheckWorktreeChanged",
                     "ACTION_CODES", "action_number"):
            self.assertIn(name, exported)
            self.assertTrue(hasattr(domain, name))


if __name__ == "__main__":
    unittest.main()
