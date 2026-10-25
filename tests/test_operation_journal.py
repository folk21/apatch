"""Durable project-local operation runs and schema migration contracts."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apatch_lib.model import Abort, RemoteOutcomeUnknown, load_project_config
from apatch_lib.operation_events import OperationRun, RunOutcome, unresolved_runs
from apatch_lib.presentation.execution import OperationPresentation
from apatch_lib.progress import ProgressStore
from apatch_lib.state import finish_run, locked_state, read_state_snapshot, start_run
from apatch_lib.workflow import Workflow
from tests._support import LocalGitFixture, TOOL


class OperationJournalStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.path = self.root / ".apatch" / "apply_patch.state.json"
        self.path.parent.mkdir()

    def started(self, number=3):
        return OperationRun.start(number=number, mode="LOOSE", root=self.root,
                                  workflow_key="workflow-key", patch="test.zip", phase="new")

    def test_v1_reads_without_writing_and_migrates_without_losing_fields(self):
        legacy = {"schema_version": 1, "workflows": {"old": {"phase": "verified"}},
                  "future_extension": {"preserve": [1, 2, 3]}}
        self.path.write_text(json.dumps(legacy))
        original_bytes = self.path.read_bytes()
        snapshot = read_state_snapshot(self.path)
        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(snapshot["workflows"], legacy["workflows"])
        self.assertEqual(snapshot["operation_runs"], [])
        self.assertEqual(self.path.read_bytes(), original_bytes)
        with locked_state(self.path) as state:
            run_id = start_run(self.path, state, self.started())
            finish_run(self.path, state, run_id, outcome=RunOutcome.SUCCEEDED.value,
                       after={"phase": "patch_applied"})
        upgraded = json.loads(self.path.read_text())
        self.assertEqual(upgraded["schema_version"], 2)
        self.assertEqual(upgraded["workflows"], legacy["workflows"])
        self.assertEqual(upgraded["future_extension"], legacy["future_extension"])
        self.assertEqual(len(upgraded["operation_runs"]), 1)

    def test_started_survives_interruption_and_new_retry_has_distinct_id(self):
        with locked_state(self.path) as state:
            old_id = start_run(self.path, state, self.started())
        snapshot = read_state_snapshot(self.path)
        self.assertEqual([run["run_id"] for run in unresolved_runs(snapshot, self.root)], [old_id])
        with locked_state(self.path) as state:
            new_id = start_run(self.path, state, self.started())
            finish_run(self.path, state, new_id, outcome=RunOutcome.FAILED.value,
                       after={"phase": "new"})
        self.assertNotEqual(old_id, new_id)
        runs = read_state_snapshot(self.path)["operation_runs"]
        self.assertEqual([run["outcome"] for run in runs], ["STARTED", "FAILED"])
        self.assertIsNone(runs[0]["finished_at"])

    def test_invalid_v2_fails_without_overwriting_bytes(self):
        valid = self.started().data
        variants = (
            {"schema_version": 3, "workflows": {}, "operation_runs": []},
            {"schema_version": 2, "workflows": {}, "operation_runs": [valid, valid]},
            {"schema_version": 2, "workflows": {},
             "operation_runs": [dict(valid, outcome="SUCCEEDED", finished_at=None)]},
            {"schema_version": 2, "workflows": {},
             "operation_runs": [dict(valid, mode=["LOOSE"])]},
        )
        for value in variants:
            with self.subTest(value=value.get("schema_version")):
                self.path.write_text(json.dumps(value))
                before = self.path.read_bytes()
                with self.assertRaises(Abort):
                    with locked_state(self.path) as state:
                        start_run(self.path, state, self.started())
                self.assertEqual(self.path.read_bytes(), before)

    def test_two_processes_append_distinct_runs_without_losing_updates(self):
        script = (
            "from pathlib import Path\n"
            "from apatch_lib.state import locked_state, start_run, finish_run\n"
            "from apatch_lib.operation_events import OperationRun\n"
            "import sys, time\n"
            "root = Path(sys.argv[1])\n"
            "path = root / '.apatch/apply_patch.state.json'\n"
            "with locked_state(path) as state:\n"
            "    item = OperationRun.start(number=3, mode='LOOSE', root=root, "
            "workflow_key='w', patch='test.zip', phase='new')\n"
            "    run_id = start_run(path, state, item)\n"
            "    time.sleep(0.05)\n"
            "    finish_run(path, state, run_id, outcome='SUCCEEDED', after={'phase':'patch_applied'})\n"
        )
        processes = [subprocess.Popen([sys.executable, "-B", "-c", script, str(self.root)],
                                      cwd=TOOL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True) for _ in range(4)]
        for process in processes:
            output, errors = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, (output, errors))
        runs = read_state_snapshot(self.path)["operation_runs"]
        self.assertEqual(len(runs), 4)
        self.assertEqual(len({run["run_id"] for run in runs}), 4)
        self.assertEqual({run["outcome"] for run in runs}, {"SUCCEEDED"})


class OperationJournalCliTests(LocalGitFixture):
    def runs(self):
        return read_state_snapshot(self.state_path)["operation_runs"]

    def test_apl_success_records_exact_action_and_shared_progress_event_id(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        runs = self.runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["operation"], {"number": 3, "code": "APL"})
        self.assertEqual(runs[0]["outcome"], "SUCCEEDED")
        self.assertEqual(runs[0]["after"]["phase"], "patch_applied")
        self.assertIn("archive_sha256", runs[0]["verified_facts"])
        progress = ProgressStore(self.bin).read_snapshot()["events"]
        self.assertEqual(progress[0]["event_id"], runs[0]["run_id"])

    def test_sequence_has_three_runs_and_one_sequence_id(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN,CHK", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        runs = self.runs()
        self.assertEqual([run["operation"]["code"] for run in runs], ["APL", "BRN", "CHK"])
        self.assertEqual([run["sequence"]["index"] for run in runs], [1, 2, 3])
        self.assertEqual({run["sequence"]["total"] for run in runs}, {3})
        self.assertEqual(len({run["sequence"]["id"] for run in runs}), 1)
        self.assertEqual(len({run["run_id"] for run in runs}), 3)

    def test_cancelled_confirmation_records_cancelled_not_success(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("op=APL", selection=stem, text="n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.runs()[0]["outcome"], "CANCELLED")
        self.assertNotIn("verified_facts", self.runs()[0])

    def test_failed_action_still_creates_run_with_bounded_error(self):
        result = self.invoke_cli("op=PR")
        self.assertEqual(result.returncode, 2)
        runs = self.runs()
        self.assertEqual(runs[0]["outcome"], "FAILED")
        self.assertEqual(runs[0]["error"]["category"], "ACTION_FAILED")
        self.assertNotIn("Traceback", json.dumps(runs))

    def test_declined_merge_and_uncertain_pr_keep_distinct_outcomes(self):
        from apatch_lib.model import load_config, load_handoff
        config = load_project_config(self.root, load_config(TOOL))
        handoff = load_handoff(self.params)
        with locked_state(config.state_path) as state:
            workflow = Workflow(self.root, config, handoff, state, loose=True,
                                skip_previous_cycles=True)
            with patch.object(OperationPresentation, "interactive", return_value="CANCELLED"):
                self.assertEqual(workflow.interactive("MRG"), "CANCELLED")
            with patch.object(OperationPresentation, "interactive",
                              side_effect=RemoteOutcomeUnknown("token=private")):
                with self.assertRaises(RemoteOutcomeUnknown):
                    workflow.interactive("PR")
        runs = self.runs()
        self.assertEqual([run["outcome"] for run in runs], ["CANCELLED", "INDETERMINATE"])
        self.assertNotIn("token=private", json.dumps(runs))
        self.assertNotIn("verified_facts", runs[1])

    def test_no_op_and_keyboard_interrupt_do_not_claim_verified_effects(self):
        from apatch_lib.model import load_config, load_handoff
        config = load_project_config(self.root, load_config(TOOL))
        handoff = load_handoff(self.params)
        with locked_state(config.state_path) as state:
            workflow = Workflow(self.root, config, handoff, state, loose=True,
                                skip_previous_cycles=True)
            with patch.object(OperationPresentation, "interactive", return_value="NO_OP"):
                self.assertEqual(workflow.interactive("CHK"), "NO_OP")
            with patch.object(OperationPresentation, "interactive", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    workflow.interactive("PSH")
        runs = self.runs()
        self.assertEqual([run["outcome"] for run in runs], ["NO_OP", "INTERRUPTED"])
        self.assertTrue(all("verified_facts" not in run for run in runs))

    def test_read_only_status_reports_unresolved_run_without_rewriting_state(self):
        with locked_state(self.state_path) as state:
            run_id = start_run(self.state_path, state, OperationRun.start(
                number=7, mode="LOOSE", root=self.root, workflow_key="known",
                patch="test.zip", phase="pushed"))
        before = self.state_path.read_bytes()
        result = self.invoke_cli("op=STS")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(run_id, result.stdout)
        self.assertIn("remain STARTED", result.stdout)
        self.assertEqual(self.state_path.read_bytes(), before)
