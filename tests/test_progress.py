"""Tool-global progress persistence, safety, recovery, and CLI integration."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._support import LocalGitFixture, TOOL
from apatch_lib.model import Abort
from apatch_lib.progress import ProgressEvent, ProgressStore, utc_now


def event_for(root, result="SUCCESS", operation=4, sequence=None, error=None):
    return ProgressEvent.capture(
        root=root, patch_file="test-patch.zip", operation_number=operation,
        mode="loose", result=result, phase_before="patch_applied",
        phase_after="verified" if result == "SUCCESS" else "patch_applied",
        branch_before="feature/testing", branch_after="feature/testing",
        record={"commit_sha": None, "pr_number": None},
        started_at_utc=utc_now(), duration_seconds=0.12,
        sequence=sequence, error=error)


class ProgressStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.tool = Path(self.temporary.name) / "installed-tool"
        self.tool.mkdir()
        self.root = Path(self.temporary.name) / "repositories" / "alpha"
        self.root.mkdir(parents=True)
        self.store = ProgressStore(self.tool)

    def test_first_event_creates_private_master_and_project_view(self):
        event = event_for(self.root)
        self.assertEqual(self.store.read_snapshot()["events"], [])
        self.store.append_event(event)
        master = self.store.read_snapshot()
        self.assertEqual(len(master["events"]), 1)
        self.assertEqual(master["events"][0]["operation_code"], "CHK")
        project = next(iter(master["projects"].values()))
        history = self.store.directory / project["history_file"]
        self.assertEqual(json.loads(history.read_text())["events"], master["events"])
        self.assertEqual(stat.S_IMODE(self.store.master_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(history.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.store.directory.stat().st_mode), 0o700)

    def test_idempotent_event_replay_and_regeneration(self):
        event = event_for(self.root)
        self.store.append_event(event)
        project = next(iter(self.store.read_snapshot()["projects"].values()))
        history = self.store.directory / project["history_file"]
        history.write_text("malformed derivative")
        self.store.append_event(event)
        self.assertEqual(len(self.store.read_snapshot()["events"]), 1)
        self.assertEqual(json.loads(history.read_text())["events"][0]["event_id"], event.data["event_id"])

    def test_interrupted_derived_write_keeps_master_and_repairs_on_next_append(self):
        event = event_for(self.root)
        self.store.append_event(event)
        project = next(iter(self.store.read_snapshot()["projects"].values()))
        history = self.store.directory / project["history_file"]
        victim = Path(self.temporary.name) / "unrelated-file"
        victim.write_text("unchanged")
        history.unlink()
        history.symlink_to(victim)
        second = event_for(self.root)
        with self.assertRaises(Abort):
            self.store.append_event(second)
        self.assertEqual(len(self.store.read_snapshot()["events"]), 2)
        self.assertEqual(victim.read_text(), "unchanged")
        history.unlink()
        self.store.append_event(second)
        self.assertEqual(len(json.loads(history.read_text())["events"]), 2)

    def test_two_roots_same_basename_remain_separate(self):
        other = Path(self.temporary.name) / "another" / "alpha"
        other.mkdir(parents=True)
        self.store.append_event(event_for(self.root))
        self.store.append_event(event_for(other))
        master = self.store.read_snapshot()
        self.assertEqual(len(master["projects"]), 2)
        filenames = {project["history_file"] for project in master["projects"].values()}
        self.assertEqual(len(filenames), 2)
        self.assertIn("alpha_progress.json", filenames)
        for project in master["projects"].values():
            own = json.loads((self.store.directory / project["history_file"]).read_text())
            self.assertEqual(len(own["events"]), 1)
            self.assertEqual(own["events"][0]["project_root"], project["root"])

    def test_corrupted_master_is_never_replaced(self):
        self.store.append_event(event_for(self.root))
        self.store.master_path.write_text("{bad json")
        with self.assertRaises(Abort):
            self.store.append_event(event_for(self.root))
        self.assertEqual(self.store.master_path.read_text(), "{bad json")

    def test_master_and_derived_symlinks_are_refused(self):
        victim = Path(self.temporary.name) / "important.txt"
        victim.write_text("must remain unchanged")
        self.store.directory.mkdir(parents=True)
        self.store.master_path.symlink_to(victim)
        with self.assertRaises(Abort):
            self.store.append_event(event_for(self.root))
        self.assertEqual(victim.read_text(), "must remain unchanged")
        self.store.master_path.unlink()
        self.store.append_event(event_for(self.root))
        history = next(iter(self.store.read_snapshot()["projects"].values()))["history_file"]
        path = self.store.directory / history
        path.unlink()
        path.symlink_to(victim)
        with self.assertRaises(Abort):
            self.store.append_event(event_for(self.root))
        self.assertEqual(victim.read_text(), "must remain unchanged")

    def test_event_is_bounded_redacted_and_sequence_aware(self):
        error = Abort("SECRET_TOKEN=secret value and complete command arguments")
        event = event_for(self.root, result="UNKNOWN_REMOTE_RESULT", operation=7,
                          sequence=("test-sequence", 2, 5), error=error)
        self.store.append_event(event)
        entry = self.store.read_snapshot()["events"][0]
        self.assertEqual(entry["sequence_id"], "test-sequence")
        self.assertEqual(entry["step_index"], 2)
        self.assertEqual(entry["step_total"], 5)
        self.assertIsNone(entry["next_suggested"])
        self.assertNotIn("SECRET_TOKEN", json.dumps(entry))
        self.assertEqual(entry["result"], "UNKNOWN_REMOTE_RESULT")

    def test_two_subprocesses_append_without_lost_updates(self):
        script = (
            "import sys; from pathlib import Path; "
            "from apatch_lib.progress import ProgressStore, ProgressEvent, utc_now; "
            "root=Path(sys.argv[2]); "
            "event=ProgressEvent.capture(root=root, patch_file='synthetic.zip', "
            "operation_number=4, mode='loose', result='SUCCESS', "
            "phase_before='patch_applied', phase_after='verified', "
            "branch_before='main', branch_after='main', record={}, "
            "started_at_utc=utc_now(), duration_seconds=0.01); "
            "ProgressStore(Path(sys.argv[1])).append_event(event)"
        )
        commands = [subprocess.Popen([sys.executable, "-B", "-c", script,
                                      str(self.tool), str(self.root)], cwd=TOOL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for _ in range(4)]
        for process in commands:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, (stdout, stderr))
        self.assertEqual(len(self.store.read_snapshot()["events"]), 4)


class ProgressCliTests(LocalGitFixture):
    def test_cli_direct_action_creates_history_under_tool_installation_only(self):
        self.make_self_contained_zip()
        outcome = self.invoke_zip("--op=APL", "--skip-approves=true", selection=self.zip.stem)
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        store = ProgressStore(self.bin)
        entries = store.read_snapshot()["events"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["operation_code"], "APL")
        self.assertEqual(entries[0]["result"], "SUCCESS")
        self.assertFalse((self.root / ".apatch" / "progress").exists())

    def test_cli_failed_action_records_failure_without_secret_text(self):
        outcome = self.invoke_cli("--op=7")
        self.assertEqual(outcome.returncode, 2)
        entries = ProgressStore(self.bin).read_snapshot()["events"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["result"], "FAILED")
        self.assertEqual(entries[0]["operation_code"], "PR")

    def test_declined_confirmation_is_recorded_as_cancelled(self):
        self.make_self_contained_zip()
        result = self.invoke_zip("--op=APL", selection=self.zip.stem, text="n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = ProgressStore(self.bin).read_snapshot()["events"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["operation_code"], "APL")
        self.assertEqual(entries[0]["result"], "CANCELLED")

    def test_cli_sequence_records_each_attempt_and_identity(self):
        self.make_self_contained_zip()
        outcome = self.invoke_zip("--op-seq=APL,BRN,CHK", "--skip-approves=true",
                                  selection=self.zip.stem)
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        entries = ProgressStore(self.bin).read_snapshot()["events"]
        self.assertEqual([item["operation_code"] for item in entries], ["APL", "BRN", "CHK"])
        self.assertEqual([item["step_index"] for item in entries], [1, 2, 3])
        self.assertEqual(len({item["sequence_id"] for item in entries}), 1)

    def test_status_records_activity_without_changing_project_checkpoint(self):
        self.make_self_contained_zip()
        first = self.invoke_zip("--op=APL", "--skip-approves=true", selection=self.zip.stem)
        self.assertEqual(first.returncode, 0, first.stderr)
        checkpoint = self.state_path.read_bytes()
        result = self.invoke_zip("--op=STS")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state_path.read_bytes(), checkpoint)
        entries = ProgressStore(self.bin).read_snapshot()["events"]
        self.assertEqual([item["operation_code"] for item in entries], ["APL", "STS"])
        self.assertEqual(entries[-1]["result"], "SUCCESS")

    def test_unavailable_global_progress_warns_without_rejecting_applied_patch(self):
        self.make_self_contained_zip()
        (self.bin / ".apatch").mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        (self.bin / ".apatch" / "progress").symlink_to(outside, target_is_directory=True)
        result = self.invoke_zip("--op=APL", "--skip-approves=true", selection=self.zip.stem)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PROGRESS_UNAVAILABLE", result.stdout)
        self.assertTrue(self.state_path.exists())
        self.assertEqual(list(outside.iterdir()), [])
