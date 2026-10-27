"""AS-03 action-result contracts across presentation and durable journals."""

import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apatch_lib.core.contracts import ActionResult
from apatch_lib.core.enums import OperationOutcome
from apatch_lib.model import Abort, RemoteOutcomeUnknown
from apatch_lib.operation_events import RunOutcome, journal_outcome_for_result
from apatch_lib.presentation.execution import OperationPresentation


class ActionResultTests(unittest.TestCase):
    def test_explicit_evidence_determines_result_independently_of_git(self) -> None:
        cases = (
            (True, False, OperationOutcome.SUCCESS),
            (False, False, OperationOutcome.NO_OP),
            (None, False, OperationOutcome.NO_OP),
            (True, True, OperationOutcome.CANCELLED),
            (ActionResult.already_satisfied("remote verified"), False,
             OperationOutcome.ALREADY_SATISFIED),
        )
        for value, declined, expected in cases:
            with self.subTest(value=value, declined=declined):
                self.assertEqual(ActionResult.completed(
                    value, declined=declined).outcome, expected)

    def test_unrecognized_legacy_result_cannot_be_assumed_successful(self) -> None:
        with self.assertRaises(TypeError):
            ActionResult.completed("done", declined=False)

    def test_unknown_remote_result_outweighs_stale_decline_flag(self) -> None:
        result = ActionResult.failed(RemoteOutcomeUnknown("HTTP 504"), declined=True)
        self.assertEqual(result.outcome, OperationOutcome.UNKNOWN_REMOTE_RESULT)
        self.assertEqual(result.progress_outcome, "UNKNOWN_REMOTE_RESULT")

    def test_partial_local_effect_does_not_claim_action_completion(self) -> None:
        result = ActionResult.partial("Local base synchronized; PR unverified")
        self.assertEqual(result.outcome, OperationOutcome.NO_OP)
        self.assertTrue(result.confirmed_partial_effect)
        self.assertEqual(result.progress_outcome, "NO_OP")

    def test_public_outcomes_map_into_existing_journal_schema(self) -> None:
        expected = {
            OperationOutcome.SUCCESS: RunOutcome.SUCCEEDED,
            OperationOutcome.ALREADY_SATISFIED: RunOutcome.NO_OP,
            OperationOutcome.NO_OP: RunOutcome.NO_OP,
            OperationOutcome.ERROR: RunOutcome.FAILED,
            OperationOutcome.CANCELLED: RunOutcome.CANCELLED,
            OperationOutcome.UNKNOWN_REMOTE_RESULT: RunOutcome.INDETERMINATE,
        }
        for public, journal in expected.items():
            with self.subTest(public=public):
                self.assertEqual(journal_outcome_for_result(public), journal.value)
        self.assertEqual(ActionResult.already_satisfied("synced").progress_outcome, "NO_OP")


class ActionExecutorTests(unittest.TestCase):
    def test_unavailable_action_does_not_call_mutation(self) -> None:
        from apatch_lib.action_executor import execute_workflow_action

        mutate = Mock()
        with self.assertRaisesRegex(Abort, "Action unavailable"):
            execute_workflow_action(SimpleNamespace(), 5, mutate, "requires verified phase", "new")
        mutate.assert_not_called()

    def test_previous_cycles_link_only_after_explicitly_confirmed_apply(self) -> None:
        from apatch_lib import action_executor

        previous = ("older-workflow",)
        workflow = SimpleNamespace(
            loose=False, skip_previous_cycles=False, phase="new",
            record={"archive_sha256": "sha"},
            branch_patch=SimpleNamespace(assert_patch_order=Mock(),
                                         block_unattended_duplicate=Mock()),
            inspect_previous_cycles=Mock(return_value=previous),
            link_successful_previous_cycles=Mock(),
        )

        def no_completion() -> None:
            workflow.phase = "patch_applied"

        with patch.object(action_executor, "confirmation_was_declined", return_value=False):
            result = action_executor.execute_workflow_action(
                workflow, 3, no_completion, None, "new")
        self.assertEqual(result.outcome, OperationOutcome.NO_OP)
        workflow.link_successful_previous_cycles.assert_not_called()

        with patch.object(action_executor, "confirmation_was_declined", return_value=False):
            result = action_executor.execute_workflow_action(
                workflow, 3, lambda: True, None, "new")
        self.assertEqual(result.outcome, OperationOutcome.SUCCESS)
        workflow.link_successful_previous_cycles.assert_called_once_with(previous)


class _PresentationHarness(OperationPresentation):
    def __init__(self, evidence: object) -> None:
        self.evidence = evidence
        self.root = Path("/unused-mocked-repository")
        self.handoff = SimpleNamespace(branch="feature/test", patch="test.zip")
        self.config = SimpleNamespace(base="main")
        self.record: dict[str, object] = {}
        self.force = False
        self.loose = False
        self.phase = "verified"
        self.skip_previous_cycles = True
        self.progress_sequence = None
        self.operation_run_id = None
        self.progress_results: list[str] = []

    def options(self) -> list[tuple[str, Callable[[], object], str | None]]:
        return [("Verified action", self._complete, None) for _ in range(9)]

    def _complete(self) -> object:
        return self.evidence

    def _record_progress(self, number: int, started_at: str,
                         elapsed: float, result: str, before_phase: str,
                         before_branch: str, after_branch: str, *,
                         error: BaseException | None = None) -> None:
        self.progress_results.append(result)


class PresentationResultTests(unittest.TestCase):
    def _perform(self, evidence: object, *, declined: bool = False) -> tuple[str, list[str]]:
        from apatch_lib import action_executor
        from apatch_lib.presentation import execution

        harness = _PresentationHarness(evidence)
        with patch.object(execution, "current_branch", return_value="feature/test"), \
                patch.object(execution, "head", return_value="a" * 40), \
                patch.object(execution, "status_paths", return_value={}), \
                patch.object(execution, "confirmation_was_declined", return_value=declined), \
                patch.object(action_executor, "confirmation_was_declined", return_value=declined), \
                patch.object(execution, "inspect_patch"), \
                patch.object(execution, "display_recommendation"):
            result = harness.interactive("CHK", show_header=False)
        return result, harness.progress_results

    def test_repeated_check_with_identical_git_snapshot_is_success(self) -> None:
        outcome, progress = self._perform(True)
        self.assertEqual((outcome, progress), ("SUCCESS", ["SUCCESS"]))

    def test_action_without_completion_evidence_is_not_success(self) -> None:
        outcome, progress = self._perform(None)
        self.assertEqual((outcome, progress), ("NO_OP", ["NO_OP"]))

    def test_unconfirmed_git_change_fails_closed_and_records_failure(self) -> None:
        from apatch_lib.presentation import execution

        harness = _PresentationHarness(None)
        with patch.object(execution, "current_branch", return_value="feature/test"), \
                patch.object(execution, "head", side_effect=["a" * 40, "b" * 40]), \
                patch.object(execution, "status_paths", return_value={}), \
                patch.object(execution, "inspect_patch"), \
                patch.object(execution, "display_recommendation"):
            with self.assertRaisesRegex(Abort, "UNCONFIRMED_LOCAL_RESULT"):
                harness.interactive("CMT", show_header=False)
        self.assertEqual(harness.progress_results, ["FAILED"])

    def test_confirmed_partial_effect_keeps_progress_as_no_op(self) -> None:
        from apatch_lib.presentation import execution

        harness = _PresentationHarness(ActionResult.partial("Local base synchronized"))
        with patch.object(execution, "current_branch", side_effect=["feature/test", "main"]), \
                patch.object(execution, "head", return_value="a" * 40), \
                patch.object(execution, "status_paths", return_value={}), \
                patch.object(execution, "inspect_patch"), \
                patch.object(execution, "display_recommendation"):
            result = harness.interactive("SYN", show_header=False)
        self.assertEqual(result, "NO_OP")
        self.assertEqual(harness.progress_results, ["NO_OP"])

    def test_declined_action_is_cancelled_despite_positive_evidence(self) -> None:
        outcome, progress = self._perform(True, declined=True)
        self.assertEqual((outcome, progress), ("CANCELLED", ["CANCELLED"]))

    def test_previously_verified_sync_preserves_legacy_progress_mapping(self) -> None:
        from apatch_lib.presentation import execution

        harness = _PresentationHarness(ActionResult.already_satisfied("PR verified"))
        with patch.object(execution, "current_branch", return_value="main"), \
                patch.object(execution, "head", return_value="a" * 40), \
                patch.object(execution, "status_paths", return_value={}), \
                patch.object(execution, "inspect_patch"), \
                patch.object(execution, "display_recommendation"):
            result = harness.interactive("SYN", show_header=False)
        self.assertEqual(result, "ALREADY_SATISFIED")
        self.assertEqual(harness.progress_results, ["NO_OP"])


if __name__ == "__main__":
    unittest.main()
