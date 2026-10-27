"""Explicit applied ZIP selection and replay-free sequence regression cases."""

import json
import zipfile

from tests._support import LocalGitFixture, command


class ExplicitZipResumeTests(LocalGitFixture):
    def prepare_applied_zip(self, *, transfer=True):
        stem = self.make_self_contained_zip()
        actions = "APL,BRN" if transfer else "APL"
        result = self.invoke_zip(f"opSeq={actions}", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return stem

    def test_explicit_zip_can_resume_checks_when_cache_is_missing(self):
        stem = self.prepare_applied_zip()
        cached = self.root / ".apatch" / "params.json"
        cached.unlink()
        before = self.history_path.read_bytes()
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Verified selected ZIP", result.stdout)
        self.assertIn("SEQUENCE REPORT 10 [STS]", result.stdout)
        self.assertEqual(self.history_path.read_bytes(), before)
        self.assertEqual(json.loads(cached.read_text())["patch_file"], self.zip.name)

    def test_check_script_repair_can_add_new_files_before_explicit_resume(self):
        stem = self.prepare_applied_zip()
        self.project_config.write_text('schema_version: 1\nchecks:\n  - ["./new_checks.sh"]\n')
        failed = self.invoke_zip("op=CHK", "skipApproves=true")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("new_checks.sh", failed.stderr + failed.stdout)
        script = self.root / "new_checks.sh"
        script.write_text("#!/bin/sh\nset -eu\ntest -f new.txt\n")
        script.chmod(0o755)
        resumed = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        self.assertEqual(script.read_text(), "#!/bin/sh\nset -eu\ntest -f new.txt\n")
        self.assertIn("Canonical checks passed", resumed.stdout)

    def test_apl_and_brn_prefix_are_satisfied_without_replaying_archive(self):
        stem = self.prepare_applied_zip()
        before_source = (self.root / "existing.txt").read_bytes()
        before_history = self.history_path.read_bytes()
        before_head = self.head
        result = self.invoke_zip("opSeq=APL,BRN,CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Already satisfied: 3 [APL], 1 [BRN]", result.stdout)
        self.assertEqual((self.root / "existing.txt").read_bytes(), before_source)
        self.assertEqual(self.history_path.read_bytes(), before_history)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), before_head)
        runs = json.loads(self.state_path.read_text())["operation_runs"]
        applied_attempts = [run for run in runs if run["operation"]["number"] == 3]
        self.assertEqual([run["outcome"] for run in applied_attempts], ["SUCCEEDED", "NO_OP"])

    def test_pending_zip_first_branch_transfer_is_not_marked_satisfied(self):
        stem = self.prepare_applied_zip(transfer=False)
        result = self.invoke_zip("opSeq=APL,BRN,CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Already satisfied: 3 [APL]", result.stdout)
        self.assertNotIn("Already satisfied: 3 [APL], 1 [BRN]", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "feature/test-local-handoff")

    def test_unknown_zip_cannot_start_with_checks_or_change_runtime_state(self):
        stem = self.make_self_contained_zip()
        self.assertFalse(self.state_path.exists())
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("No completed application checkpoint", result.stderr)
        self.assertFalse(self.state_path.exists())
        self.assertFalse((self.root / ".apatch" / "params.json").exists())

    def test_changed_zip_digest_refuses_resume_before_touching_cached_handoff(self):
        stem = self.prepare_applied_zip()
        cached = self.root / ".apatch" / "params.json"
        before_cache = cached.read_bytes()
        before_history = self.history_path.read_bytes()
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr("example_service/tampered.txt", "not applied\n")
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Selected ZIP identity or digest conflicts", result.stderr)
        self.assertEqual(cached.read_bytes(), before_cache)
        self.assertEqual(self.history_path.read_bytes(), before_history)
        self.assertFalse((self.root / "tampered.txt").exists())

    def test_wrong_branch_refuses_explicit_resume_without_replaying(self):
        stem = self.prepare_applied_zip()
        command("git", "switch", "main", cwd=self.root)
        previous = self.history_path.read_bytes()
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Current branch main does not match", result.stderr)
        self.assertEqual(self.history_path.read_bytes(), previous)

    def test_missing_apl_run_does_not_prove_an_old_checkpoint(self):
        stem = self.prepare_applied_zip()
        state = json.loads(self.state_path.read_text())
        state["operation_runs"] = [run for run in state["operation_runs"]
                                   if run["operation"]["number"] != 3]
        self.state_path.write_text(json.dumps(state))
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("matching successful APL journal run is missing", result.stderr)

    def test_direct_reapplication_still_obeys_duplicate_guard(self):
        stem = self.prepare_applied_zip()
        result = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("already", result.stderr.lower() + result.stdout.lower())

    def test_numeric_sequence_resume_keeps_strict_and_force_mode_guards(self):
        stem = self.prepare_applied_zip()
        for mode in ("--strict", "--force"):
            with self.subTest(mode=mode):
                result = self.invoke_zip(mode, "opSeq=3,1,4,10", "skipApproves=true",
                                         selection=stem)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn("Already satisfied: 3 [APL], 1 [BRN]", result.stdout)

    def test_valid_but_different_cached_zip_is_replaced_after_verified_selection(self):
        stem = self.prepare_applied_zip()
        cached = self.root / ".apatch" / "params.json"
        payload = json.loads(cached.read_text())
        payload.update(patch_file="different.zip", patch_sha256="0" * 64)
        cached.write_text(json.dumps(payload))
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(cached.read_text())["patch_file"], self.zip.name)

    def test_duplicate_applied_history_refuses_zip_selection(self):
        stem = self.prepare_applied_zip()
        prior = self.history_path.read_text()
        self.history_path.write_text(prior + "\n" + prior)
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicated", result.stderr)
        self.assertEqual(self.history_path.read_text(), prior + "\n" + prior)

    def test_symlinked_history_cannot_be_used_as_resume_evidence(self):
        stem = self.prepare_applied_zip()
        previous = self.history_path.read_bytes()
        victim = self.base / "history-copy.txt"
        victim.write_bytes(previous)
        self.history_path.unlink()
        self.history_path.symlink_to(victim)
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Runtime state and history files must not be symlinks", result.stderr)
        self.assertEqual(victim.read_bytes(), previous)

    def test_remote_identity_drift_prevents_reselection(self):
        stem = self.prepare_applied_zip()
        command("git", "remote", "set-url", "origin", str(self.base / "other-remote.git"),
                cwd=self.root)
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Configured remote identity has changed", result.stderr)

    def test_followup_zip_uses_its_own_application_journal_for_resume(self):
        first = self.prepare_applied_zip()
        second = self.make_followup_zip()
        applied = self.invoke_zip("followup=true", "op=APL", "skipApproves=true",
                                  selection=second.stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        followup = self.invoke_zip("opSeq=APL,BRN,CHK,STS", "skipApproves=true",
                                   selection=second.stem)
        self.assertEqual(followup.returncode, 0, followup.stderr + followup.stdout)
        self.assertIn("Already satisfied: 3 [APL], 1 [BRN]", followup.stdout)
        self.assertIn("Patch: " + second.name, followup.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "second revision\n")
        self.assertNotEqual(first, second.stem)

    def test_older_zip_cannot_be_reselected_after_successful_followup(self):
        first = self.prepare_applied_zip()
        second = self.make_followup_zip()
        applied = self.invoke_zip("followup=true", "op=APL", "skipApproves=true",
                                  selection=second.stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        cached = self.root / ".apatch" / "params.json"
        previous_cache = cached.read_bytes()
        previous_history = self.history_path.read_bytes()
        denied = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=first)
        self.assertEqual(denied.returncode, 2)
        self.assertIn("newer continuation", denied.stderr)
        self.assertEqual(cached.read_bytes(), previous_cache)
        self.assertEqual(self.history_path.read_bytes(), previous_history)

    def test_interrupted_application_cannot_be_mistaken_for_satisfied_apl(self):
        stem = self.prepare_applied_zip()
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        record["phase"] = "applying"
        self.state_path.write_text(json.dumps(state))
        result = self.invoke_zip("opSeq=APL,BRN", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("No completed application checkpoint", result.stderr)

    def test_symlinked_cache_refuses_reselection_without_touching_target(self):
        stem = self.prepare_applied_zip()
        cached = self.root / ".apatch" / "params.json"
        cached.unlink()
        victim = self.base / "user-file.txt"
        victim.write_text("do not overwrite\n")
        cached.symlink_to(victim)
        result = self.invoke_zip("opSeq=CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsafe cached handoff path", result.stderr)
        self.assertEqual(victim.read_text(), "do not overwrite\n")
