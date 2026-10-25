"""Regression tests for the status subsystem."""

from tests._support import (
    LocalGitFixture, command, TOOL, hashlib,
    json, os, re, shlex,
    shutil, stat, subprocess, sys,
    tempfile, unittest, zipfile, redirect_stdout,
    replace, datetime, StringIO, Path,
    patch, Abort, RemoteOutcomeUnknown, load_handoff,
    load_project_config, safe_relative, inspect, load_config,
    AppliedPatchHistory, ACTION_CODES, action_number, OperationSequence,
    execute_sequence, outcome_label,
)


class StatusTests(LocalGitFixture):
    def test_status_is_read_only_before_first_workflow_and_does_not_need_zip(self):
        self.zip.unlink()
        exclude = self.root / ".git" / "info" / "exclude"
        before_exclude = exclude.read_bytes()
        before_ref = command("git", "rev-parse", "HEAD", cwd=self.root).stdout
        result = self.invoke_cli("op=STS", "--strict")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PATCH STATUS 10 [STS]", result.stdout)
        self.assertIn("Recorded phase: new", result.stdout)
        self.assertIn("Next suggested: 1 [BRN]", result.stdout)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.lock_path.exists())
        self.assertFalse(self.log_path.exists())
        self.assertEqual(exclude.read_bytes(), before_exclude)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout, before_ref)

    def test_status_reports_applied_patch_and_next_action_without_mutation(self):
        created = self.invoke_cli("--strict", "op=BAP", "skipApproves=true")
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertIn("Next suggested: 4 [CHK]", created.stdout)
        saved_state = self.state_path.read_bytes()
        saved_history = self.history_path.read_bytes()
        saved_lock = self.lock_path.read_bytes()
        before_status = command("git", "status", "--porcelain", cwd=self.root).stdout
        before_refs = command("git", "show-ref", cwd=self.root).stdout
        self.zip.unlink()
        result = self.invoke_cli("--strict", "op=10")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Branch origin: CREATED [RECORDED]", result.stdout)
        self.assertIn("Patch applied: YES [RECORDED]", result.stdout)
        self.assertIn("Commit: PENDING", result.stdout)
        self.assertIn("Pull request: UNKNOWN [UNKNOWN]", result.stdout)
        self.assertIn("Next suggested: 4 [CHK]", result.stdout)
        self.assertEqual(self.state_path.read_bytes(), saved_state)
        self.assertEqual(self.history_path.read_bytes(), saved_history)
        self.assertEqual(self.lock_path.read_bytes(), saved_lock)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, before_status)
        self.assertEqual(command("git", "show-ref", cwd=self.root).stdout, before_refs)

    def test_status_uses_unique_stored_workflow_when_cache_is_absent(self):
        self.assertEqual(self.invoke_cli("--strict", "op=BAP", "skipApproves=true").returncode, 0)
        result = subprocess.run([sys.executable, str(self.bin / "apatch.py"), "op=STS"],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(f"Patch: {self.zip.name}", result.stdout)

    def test_status_handoff_selects_exact_patch_despite_other_workflows(self):
        self.assertEqual(self.invoke_cli("--strict", "op=BAP", "skipApproves=true").returncode, 0)
        data = json.loads(self.state_path.read_text())
        another = dict(next(iter(data["workflows"].values())))
        another["patch_file"] = "another-patch.zip"
        data["workflows"]["independent-workflow-key"] = another
        self.state_path.write_text(json.dumps(data))
        selected = self.invoke_cli("op=STS")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertIn(f"Patch: {self.zip.name}", selected.stdout)
        mismatch = self.invoke_cli("op=STS", "patch=another-patch.zip")
        self.assertEqual(mismatch.returncode, 2)
        self.assertIn("does not match the supplied handoff JSON", mismatch.stderr)

    def test_missing_recorded_commit_is_conflict_not_next_action(self):
        self.assertEqual(self.invoke_cli("--strict", "op=BAP", "skipApproves=true").returncode, 0)
        data = json.loads(self.state_path.read_text())
        record = next(iter(data["workflows"].values()))
        record["phase"] = "committed"
        record["commit_sha"] = "f" * 40
        self.state_path.write_text(json.dumps(data))
        result = self.invoke_cli("--strict", "op=STS")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Commit: ffffffffffff [CONFLICT]", result.stdout)
        self.assertIn("Next suggested: NONE", result.stdout)

    def test_interactive_status_selection_does_not_persist_state(self):
        status = self.invoke("10\n")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("10. [STS]", status.stdout)
        self.assertIn("PATCH STATUS 10 [STS]", status.stdout)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.lock_path.exists())

    def test_status_does_not_invent_legacy_branch_provenance(self):
        self.assertEqual(self.invoke_cli("--strict", "op=BAP", "skipApproves=true").returncode, 0)
        data = json.loads(self.state_path.read_text())
        next(iter(data["workflows"].values())).pop("branch_origin")
        self.state_path.write_text(json.dumps(data))
        result = self.invoke_cli("--strict", "op=STS")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Branch origin: UNKNOWN [UNKNOWN]", result.stdout)

    def test_interactive_status_does_not_approve_a_changed_handoff(self):
        self.assertEqual(self.invoke_cli("--strict", "op=BAP", "skipApproves=true").returncode, 0)
        self.payload["commit_message"] = "New unapproved message"
        self.params.write_text(json.dumps(self.payload))
        state_bytes = self.state_path.read_bytes()
        status = self.invoke("STS\n")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("PATCH STATUS 10 [STS]", status.stdout)
        self.assertNotIn("Use the updated handoff", status.stdout)
        self.assertEqual(self.state_path.read_bytes(), state_bytes)

    def test_status_does_not_claim_checks_passed_after_unverified_loose_commit(self):
        self.assertEqual(self.invoke_loose("3\nYES\n").returncode, 0)
        committed = self.invoke_loose("5\nYES\nYES\n")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        result = self.invoke_cli("--loose", "op=STS")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Recorded phase: committed", result.stdout)
        self.assertIn("Checks passed: UNKNOWN [UNKNOWN]", result.stdout)
        self.assertIn("Next suggested: 6 [PSH]", result.stdout)
