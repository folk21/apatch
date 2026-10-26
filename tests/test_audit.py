"""Read-only global patch reconciliation and command-surface regression tests."""

import json
import subprocess
import sys
from unittest.mock import patch

from tests._support import LocalGitFixture, command
from apatch_lib.model import Abort
from apatch_lib.operation_events import OperationRun
from apatch_lib.progress import ProgressEvent, ProgressStore, utc_now
from apatch_lib.reconciliation import audit_repository, format_audit
from apatch_lib.model import load_config, load_project_config


class AuditTests(LocalGitFixture):
    def invoke_unbound(self, *arguments, text=""):
        return subprocess.run([sys.executable, str(self.bin / "apatch.py"), *arguments],
                              cwd=self.root, input=text, capture_output=True, text=True)

    def _config(self):
        return load_project_config(self.root, load_config(self.bin))

    def _state(self, patch_name, *, phase="committed", commit_sha=None, branch="feature/recorded"):
        record = {"repository": str(self.root.resolve()), "patch_file": patch_name,
                  "branch": branch, "applied_branch": branch, "phase": phase}
        if commit_sha:
            record["commit_sha"] = commit_sha
        self.state_path.write_text(json.dumps({"schema_version": 1, "workflows": {"old": record}}))

    def test_audit_without_handoff_is_read_only_and_offline(self):
        self.zip.unlink()
        exclude = self.root / ".git" / "info" / "exclude"
        index = self.root / ".git" / "index"
        before = (exclude.read_bytes(), command("git", "show-ref", cwd=self.root).stdout,
                  command("git", "status", "--porcelain", cwd=self.root).stdout)
        index_bytes = index.read_bytes()
        index_mtime = index.stat().st_mtime_ns
        result = self.invoke_unbound("op=AUD")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PATCH AUDIT 11 [AUD]", result.stdout)
        self.assertIn("NO_CREATED_REGISTRY", result.stdout)
        self.assertIn("Remote: UNKNOWN (offline", result.stdout)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.lock_path.exists())
        self.assertFalse(self.history_path.exists())
        self.assertFalse(self.log_path.exists())
        self.assertFalse((self.root / ".apatch" / "params.json").exists())
        self.assertEqual(exclude.read_bytes(), before[0])
        self.assertEqual(index.read_bytes(), index_bytes)
        self.assertEqual(index.stat().st_mtime_ns, index_mtime)
        self.assertEqual(command("git", "show-ref", cwd=self.root).stdout, before[1])
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, before[2])

    def test_audit_shows_attempted_and_successful_operations_for_known_projects(self):
        other = self.base / "other_service"
        other.mkdir()
        store = ProgressStore(self.bin)

        def record(root, number, result, phase, timestamp):
            event = ProgressEvent.capture(
                root=root, patch_file="example-PATCH.zip", operation_number=number,
                mode="LOOSE", result=result, phase_before=phase, phase_after=phase,
                branch_before="feature/example", branch_after="feature/example",
                record={}, started_at_utc=utc_now(), duration_seconds=0.1)
            event.data["finished_at_utc"] = timestamp
            store.append_event(event)

        record(self.root, 3, "SUCCESS", "patch_applied", "2026-10-26T10:00:00.000Z")
        record(self.root, 4, "FAILED", "patch_applied", "2026-10-26T10:01:00.000Z")
        record(other, 9, "SUCCESS", "synced", "2026-10-26T10:02:00.000Z")
        original = store.master_path.read_bytes()

        result = self.invoke_unbound("op=11")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("APATCH GLOBAL PROGRESS [RECORDED]", result.stdout)
        self.assertIn("PATCH AUDIT 11 [AUD]", result.stdout)
        self.assertIn("Projects: 2", result.stdout)
        self.assertIn("Last attempted [RECORDED]: CHK / FAILED", result.stdout)
        self.assertIn("Last successful [RECORDED]: APL", result.stdout)
        self.assertIn("Last successful [RECORDED]: SYN", result.stdout)
        self.assertIn("other_service", result.stdout)
        self.assertLess(result.stdout.index("APATCH GLOBAL PROGRESS"),
                        result.stdout.index("PATCH AUDIT 11 [AUD]"))
        self.assertEqual(store.master_path.read_bytes(), original)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.lock_path.exists())

    def test_unreadable_global_progress_does_not_suppress_repository_audit(self):
        progress = self.bin / ".apatch" / "progress" / "progress.json"
        progress.parent.mkdir(parents=True)
        progress.write_text("{invalid JSON")

        result = self.invoke_unbound("op=AUD")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("GLOBAL_PROGRESS_UNAVAILABLE", result.stdout)
        self.assertIn("PATCH AUDIT 11 [AUD]", result.stdout)
        self.assertEqual(progress.read_text(), "{invalid JSON")
        self.assertFalse(self.state_path.exists())

    def test_symlinked_optional_progress_does_not_suppress_audit(self):
        external = self.base / "external-progress.json"
        external.write_text("untrusted external bytes")
        progress = self.bin / ".apatch" / "progress" / "progress.json"
        progress.parent.mkdir(parents=True)
        progress.symlink_to(external)

        result = self.invoke_unbound("op=11")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("GLOBAL_PROGRESS_UNAVAILABLE", result.stdout)
        self.assertIn("PATCH AUDIT 11 [AUD]", result.stdout)
        self.assertTrue(progress.is_symlink())
        self.assertEqual(external.read_text(), "untrusted external bytes")

    def test_missing_and_out_of_order_patch(self):
        self.write_created_registry("A.zip", "B.zip", "C.zip")
        self.history_path.write_text("A.zip\nC.zip\n")
        result = self.invoke_unbound("op=11")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("MISSING_APPLICATION", result.stdout)
        self.assertIn("OUT_OF_ORDER", result.stdout)
        self.assertIn("B.zip", result.stdout)
        self.assertIn("C.zip", result.stdout)
        self.assertIn("CONFLICT", result.stdout)

    def test_duplicate_and_unregistered_patch_names_are_reported(self):
        self.write_created_registry("A.zip", "A.zip")
        self.history_path.write_text("A.zip\nA.zip\nnot-created.zip\n")
        result = self.invoke_unbound("op=AUD")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for code in ("DUPLICATE_CREATED", "DUPLICATE_APPLIED", "UNREGISTERED_APPLIED"):
            self.assertIn(code, result.stdout)

    def test_v1_state_missing_commit_and_branch_are_reported_without_upgrade(self):
        self._state("legacy.zip", commit_sha="f" * 40)
        original = self.state_path.read_bytes()
        self.history_path.write_text("legacy.zip\n")
        history = self.history_path.read_bytes()
        result = self.invoke_unbound("op=AUD")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("MISSING_LOCAL_COMMIT", result.stdout)
        self.assertIn("MISSING_LOCAL_BRANCH", result.stdout)
        self.assertIn("[CONFLICT]", result.stdout)
        self.assertEqual(self.state_path.read_bytes(), original)
        self.assertEqual(self.history_path.read_bytes(), history)
        self.assertFalse(self.lock_path.exists())

    def test_started_and_indeterminate_runs_are_not_treated_as_success(self):
        run = OperationRun.start(number=7, mode="LOOSE", root=self.root,
                                 workflow_key="old", patch="orphan.zip", phase="pushed").data
        other = dict(run, run_id="a" * 32, outcome="INDETERMINATE",
                     finished_at="2026-10-26T00:00:00Z")
        self.state_path.write_text(json.dumps({"schema_version": 2, "workflows": {},
                                               "operation_runs": [run, other]}))
        result = self.invoke_unbound("op=AUD")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("UNRESOLVED_OPERATION", result.stdout)
        self.assertIn("INDETERMINATE", result.stdout)
        self.assertIn("UNKNOWN", result.stdout)

    def test_skipped_publication_checkpoints_are_unknown_not_verified(self):
        self._state("incomplete.zip", phase="merged", commit_sha=self.head, branch="main")
        self.history_path.write_text("incomplete.zip\n")
        result = self.invoke_unbound("op=AUD")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PUSH_NOT_RECORDED", result.stdout)
        self.assertIn("PR_NOT_RECORDED", result.stdout)
        self.assertIn("UNKNOWN", result.stdout)

    def test_shared_commit_does_not_imply_one_to_one_patch_mapping(self):
        self.write_created_registry("A.zip", "B.zip")
        self.history_path.write_text("A.zip\nB.zip\n")
        self._state("A.zip", phase="synced", commit_sha=self.head, branch="main")
        state = json.loads(self.state_path.read_text())
        state["workflows"]["second"] = dict(state["workflows"]["old"], patch_file="B.zip")
        self.state_path.write_text(json.dumps(state))
        result = self.invoke_unbound("op=AUD")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("MISSING_LOCAL_COMMIT", result.stdout)
        self.assertNotIn("DUPLICATE_APPLIED", result.stdout)
        self.assertNotIn("COMMIT_NOT_RECORDED", result.stdout)

    def test_explicit_remote_option_degrades_to_unknown_when_unavailable(self):
        with patch("apatch_lib.reconciliation._remote_snapshot", side_effect=Abort("unavailable")):
            report = audit_repository(self.root, self._config(), verify_remote=True)
        result = format_audit(report)
        self.assertIn("REMOTE_UNAVAILABLE", result)
        self.assertIn("Remote: UNKNOWN", result)
        self.assertIn("NO_CREATED_REGISTRY", result)

    def test_cli_remote_opt_in_is_bounded_and_keeps_local_findings(self):
        self.write_created_registry("A.zip", "B.zip")
        self.history_path.write_text("A.zip\n")
        result = self.invoke_unbound("op=AUD", "verifyRemote=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Remote: UNKNOWN", result.stdout)
        self.assertIn("MISSING_APPLICATION", result.stdout)
        self.assertFalse(self.lock_path.exists())

    def test_opt_in_remote_matching_pr_verifies_current_revision(self):
        self.history_path.write_text("A.zip\n")
        self._state("A.zip", phase="synced", commit_sha=self.head, branch="main")
        state = json.loads(self.state_path.read_text())
        record = state["workflows"]["old"]
        record.update(pushed_sha=self.head, pr_number=12)
        self.state_path.write_text(json.dumps(state))
        pr = {"number": 12, "headRefName": "main", "baseRefName": "main",
              "headRefOid": self.head, "state": "MERGED", "mergedAt": "2026-10-26T00:00:00Z"}
        with patch("apatch_lib.reconciliation._remote_snapshot",
                   return_value=({"main": self.head}, [pr], True)):
            report = audit_repository(self.root, self._config(), verify_remote=True)
        self.assertIn("Remote: VERIFIED", format_audit(report))
        self.assertNotIn("PR_REVISION_MISMATCH", format_audit(report))
        self.assertNotIn("MERGE_NOT_CONFIRMED", format_audit(report))

    def test_cli_aliases_and_menu_without_cached_handoff(self):
        for arguments in (("op=AUD",), ("op=11",), ("opSeq=AUD",), ("opSeq=11",)):
            with self.subTest(arguments=arguments):
                result = self.invoke_unbound(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn("APATCH GLOBAL PROGRESS [RECORDED]", result.stdout)
                self.assertIn("PATCH AUDIT 11 [AUD]", result.stdout)
        menu = self.invoke_unbound(text="11\n")
        self.assertEqual(menu.returncode, 0, menu.stderr + menu.stdout)
        self.assertIn("11. [AUD]", menu.stdout)
        self.assertIn("PATCH AUDIT 11 [AUD]", menu.stdout)
        selected = self.invoke_cli(text="AUD\n")
        self.assertEqual(selected.returncode, 0, selected.stderr + selected.stdout)
        self.assertIn("PATCH AUDIT 11 [AUD]", selected.stdout)

    def test_audit_option_validation_does_not_create_runtime_files(self):
        for arguments, message in (
                (("op=CHK", "verifyRemote=true"), "only supported"),
                (("opSeq=AUD,CHK",), "AUD must run separately"),
                (("op=AUD", "patch=A.zip"), "omit handoff"),
                (("A.zip", "op=AUD"), "omit handoff")):
            with self.subTest(arguments=arguments):
                result = self.invoke_unbound(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.log_path.exists())

    def test_refuse_symlinked_created_history(self):
        source = self.base / "outside.txt"
        source.write_text("A.zip\n")
        (self.root / ".apatch" / "created_patches.txt").symlink_to(source)
        result = self.invoke_unbound("op=AUD")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must not be a symlink", result.stderr)
        self.assertEqual(source.read_text(), "A.zip\n")

    def test_dirty_user_worktree_and_runtime_bytes_are_preserved(self):
        self.write_created_registry("A.zip")
        self.history_path.write_text("A.zip\n")
        (self.root / "existing.txt").write_text("manual change\n")
        (self.root / "user-new.txt").write_text("retain\n")
        self._state("A.zip", phase="patch_applied", branch="main")
        tracked = [self.root / "existing.txt", self.root / "user-new.txt",
                   self.state_path, self.history_path, self.root / ".apatch" / "created_patches.txt"]
        bytes_before = [item.read_bytes() for item in tracked]
        refs_before = command("git", "show-ref", cwd=self.root).stdout
        result = self.invoke_unbound("op=AUD")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual([item.read_bytes() for item in tracked], bytes_before)
        self.assertEqual(command("git", "show-ref", cwd=self.root).stdout, refs_before)
        self.assertFalse(self.lock_path.exists())
