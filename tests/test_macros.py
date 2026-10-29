"""Local macro dispatch and best-effort terminal status regressions."""

import shlex
import threading
from unittest.mock import patch

from apatch_lib import macros
from apatch_lib.cli_request import parse_request
from apatch_lib.model import Abort, load_config, load_project_config
from apatch_lib.patch_history import AppliedPatchHistory
from apatch_lib.state import read_state_snapshot
from tests._support import LocalGitFixture, command


class LocalMacroTests(LocalGitFixture):
    def run_stable_check_macro(self, script, *, policy="recheck_once", prepare=None,
                               timeout=30, extra_scripts=None):
        """Install check policy on a clean local base and run an isolated ZIP macro."""
        runner = self.root / "run_checks.sh"
        runner.write_text("#!/bin/sh\nset -eu\n" + script)
        runner.chmod(0o755)
        config = ("schema_version: 1\n"
                  f"check_worktree_policy: {policy}\n"
                  f"check_timeout_seconds: {timeout}\n"
                  "checks:\n  - [\"./run_checks.sh\"]\n")
        if prepare is not None:
            config += "prepare_checks:\n  - [\"./prepare.sh\"]\n"
            prep = self.root / "prepare.sh"
            prep.write_text("#!/bin/sh\nset -eu\n" + prepare)
            prep.chmod(0o755)
        for name, content in (extra_scripts or {}).items():
            (self.root / name).write_text(content)
        self.project_config.write_text(config)
        command("git", "add", "-A", cwd=self.root)
        command("git", "commit", "-m", "Configure check policy", cwd=self.root)
        command("git", "push", "origin", "main", cwd=self.root)
        self.head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.payload["base_commit"] = self.head
        stem = self.make_self_contained_zip()
        return self.invoke_zip("op=APPLY_PATCH_CHECK", "skipApproves=true", selection=stem)

    def test_recheck_once_converges_and_freezes_the_final_index(self):
        result = self.run_stable_check_macro(
            "test -f new.txt\n"
            "if ! grep -q '^formatted$' existing.txt; then\n"
            "  printf 'formatted\\n' > existing.txt\nfi\n")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("CHECK PASS 1 UNSTABLE", result.stdout)
        self.assertIn("existing.txt", result.stdout)
        self.assertIn("file bytes", result.stdout)
        self.assertIn("CANONICAL CHECK PASS 2/2", result.stdout)
        self.assertIn("CHECK PASS 2: STABLE", result.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "formatted\n")
        self.assertEqual(command("git", "show", ":existing.txt", cwd=self.root).stdout,
                         "formatted\n")
        self.assertEqual(next(iter(self._macro_records().values()))["phase"], "verified")

    def _macro_records(self):
        return read_state_snapshot(self.state_path)["workflows"]

    def test_recheck_once_rejects_continual_mutation(self):
        result = self.run_stable_check_macro(
            "if grep -q '^alpha$' existing.txt; then\n"
            "  printf 'beta\\n' > existing.txt\nelse\n"
            "  printf 'alpha\\n' > existing.txt\nfi\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("CANONICAL CHECK PASS 2/2", result.stdout)
        self.assertIn("CHECK PASS 2 UNSTABLE", result.stdout)
        self.assertIn("CHECKS_CHANGED_WORKTREE", result.stderr)
        self.assertNotIn("verified_fingerprint", next(iter(self._macro_records().values())))

    def test_direct_chk_does_not_inherit_macro_recheck_policy(self):
        result = self.run_stable_check_macro(
            "if grep -q '^alpha$' existing.txt; then\n"
            "  printf 'beta\\n' > existing.txt\nelse\n"
            "  printf 'alpha\\n' > existing.txt\nfi\n")
        self.assertEqual(result.returncode, 2)
        direct = self.invoke_zip("op=CHK", "skipApproves=true")
        self.assertEqual(direct.returncode, 2)
        self.assertIn("CANONICAL CHECK PASS 1/1", direct.stdout)
        self.assertNotIn("CANONICAL CHECK PASS 2/", direct.stdout)
        self.assertIn("CHECKS_CHANGED_WORKTREE", direct.stderr)

    def test_direct_chk_does_not_execute_macro_prepare_commands(self):
        result = self.run_stable_check_macro(
            "grep -q '^prepared$' existing.txt\n",
            prepare="printf 'prepared\\n' > existing.txt\n")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        (self.root / "existing.txt").write_text("unprepared\n")
        direct = self.invoke_zip("op=CHK", "skipApproves=true")
        self.assertEqual(direct.returncode, 2)
        self.assertNotIn("PREPARE 1/1", direct.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "unprepared\n")

    def test_failed_second_pass_never_authorizes_verification(self):
        result = self.run_stable_check_macro(
            "if grep -q '^formatted$' existing.txt; then\n"
            "  exit 17\nfi\nprintf 'formatted\\n' > existing.txt\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("CANONICAL CHECK PASS 2/2", result.stdout)
        self.assertIn("Command failed (17)", result.stderr)
        self.assertEqual((self.root / "existing.txt").read_text(), "formatted\n")
        self.assertNotIn("verified_fingerprint", next(iter(self._macro_records().values())))

    def test_prepare_runs_once_before_staging(self):
        result = self.run_stable_check_macro(
            "grep -q '^prepared$' existing.txt\n",
            policy="stop",
            prepare="printf 'prepared\\n' > existing.txt\n")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PREPARE 1/1", result.stdout)
        self.assertIn("PREPARE: repository paths changed", result.stdout)
        self.assertIn("CANONICAL CHECK PASS 1/1", result.stdout)
        self.assertNotIn("CANONICAL CHECK PASS 2/2", result.stdout)
        self.assertEqual(command("git", "show", ":existing.txt", cwd=self.root).stdout,
                         "prepared\n")

    def test_failed_prepare_stops_and_preserves_its_edits(self):
        result = self.run_stable_check_macro(
            "test -f new.txt\n",
            prepare="printf 'prepared\\n' > existing.txt\nexit 19\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("PREPARE 1/1", result.stdout)
        self.assertIn("Command failed (19)", result.stderr)
        self.assertNotIn("CANONICAL CHECK PASS", result.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "prepared\n")

    def test_untracked_output_stops_without_deleting_files(self):
        result = self.run_stable_check_macro("printf 'generated\\n' > report.txt\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("report.txt", result.stdout)
        self.assertIn("new changed/untracked path", result.stdout)
        self.assertIn("Unclassified commit paths", result.stderr)
        self.assertEqual((self.root / "report.txt").read_text(), "generated\n")

    def test_index_only_drift_is_preserved_and_blocking(self):
        result = self.run_stable_check_macro("git update-index --chmod=+x existing.txt\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Git index entry/mode", result.stdout)
        self.assertIn("Git index changed during checks", result.stderr)
        self.assertTrue(command("git", "ls-files", "--stage", "existing.txt",
                                cwd=self.root).stdout.startswith("100755 "))

    def test_executable_bit_convergence_is_reported(self):
        result = self.run_stable_check_macro("chmod +x existing.txt\n")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("executable bit", result.stdout)
        self.assertIn("CHECK PASS 2: STABLE", result.stdout)

    def test_symlink_replacement_requires_manual_review(self):
        result = self.run_stable_check_macro(
            "if ! test -L existing.txt; then\n"
            "  rm existing.txt\n  ln -s new.txt existing.txt\nfi\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("file type", result.stdout)
        self.assertIn("Symlink identity changed during checks", result.stderr)
        self.assertEqual((self.root / "existing.txt").readlink().as_posix(), "new.txt")

    def test_symlink_change_is_blocked_before_recheck(self):
        result = self.run_stable_check_macro(
            "if ! test -L existing.txt; then\n"
            "  rm existing.txt\n  ln -s new.txt existing.txt\n"
            "else\n  ln -sf run_checks.sh existing.txt\nfi\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("file type", result.stdout)
        self.assertIn("Symlink identity changed during checks", result.stderr)
        self.assertEqual((self.root / "existing.txt").readlink().as_posix(), "new.txt")

    def test_symlink_target_change_has_path_specific_diagnostic(self):
        from apatch_lib.gitutil import WorktreeEntry, worktree_change_details

        before = {"existing.txt": WorktreeEntry(" M", (), "symlink",
                                                symlink_target="first.txt")}
        after = {"existing.txt": WorktreeEntry(" M", (), "symlink",
                                               symlink_target="second.txt")}
        self.assertEqual(worktree_change_details(before, after),
                         (("existing.txt", ("symlink target",)),))

    def test_second_pass_timeout_does_not_trigger_third_attempt(self):
        result = self.run_stable_check_macro(
            "if grep -q '^formatted$' existing.txt; then\n"
            "  sleep 3\nelse\n  printf 'formatted\\n' > existing.txt\nfi\n",
            timeout=1)
        self.assertEqual(result.returncode, 2)
        self.assertIn("CANONICAL CHECK PASS 2/2", result.stdout)
        self.assertNotIn("CANONICAL CHECK PASS 3/", result.stdout)
        self.assertIn("timed out", result.stderr)
        self.assertNotIn("verified_fingerprint", next(iter(self._macro_records().values())))

    def test_concurrent_manual_edit_is_not_reclassified_as_formatter_output(self):
        marker = self.base / "check-ready"
        edited = self.base / "edit-done"
        stop_waiting = threading.Event()
        editor_finished = threading.Event()

        def edit_while_check_runs():
            while not stop_waiting.is_set():
                if marker.exists():
                    runner = self.root / "run_checks.sh"
                    runner.write_text(runner.read_text() + "# external user edit\n")
                    edited.touch()
                    editor_finished.set()
                    return
                stop_waiting.wait(0.05)

        thread = threading.Thread(target=edit_while_check_runs)
        thread.start()
        try:
            result = self.run_stable_check_macro(
                f"touch {shlex.quote(str(marker))}\n"
                "attempts=0\n"
                f"while test ! -f {shlex.quote(str(edited))}; do\n"
                "  attempts=$((attempts + 1))\n"
                "  test \"$attempts\" -le 5 || exit 41\n"
                "  sleep 1\n"
                "done\n")
        finally:
            stop_waiting.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(editor_finished.is_set(), "The external edit did not occur during CHK")
        self.assertEqual(result.returncode, 2)
        self.assertIn("run_checks.sh", result.stdout)
        self.assertIn("Unclassified commit paths", result.stderr)
        self.assertIn("external user edit", (self.root / "run_checks.sh").read_text())

    def test_apply_patch_stops_after_verified_branch_transfer(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("op=APPLY_PATCH", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("MACRO PLAN APPLY_PATCH: APL, BRN", result.stdout)
        self.assertIn("MACRO APPLY_PATCH: SUCCESS", result.stdout)
        self.assertIn("Executed: APL, BRN", result.stdout)
        self.assertIn("final 10 [STS]", result.stdout)
        self.assertNotIn("GOAL STEP: CHK", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current",
                                 cwd=self.root).stdout.strip(), self.payload["feature_branch"])
        state = read_state_snapshot(self.state_path)
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "patch_applied")
        self.assertEqual(len(state["feature_sessions"]), 1)
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 1)

    def test_repeated_macro_and_cached_handoff_do_not_reapply(self):
        stem = self.make_self_contained_zip()
        first = self.invoke_zip("op=APPLY_PATCH", "skipApproves=true", selection=stem)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        tracked = (self.state_path, self.history_path, self.root / ".git/index")
        before = {path: path.read_bytes() for path in tracked}
        for selection in (stem, None):
            with self.subTest(selection=selection):
                repeated = self.invoke_zip("op=APPLY_PATCH", "skipApproves=true",
                                           selection=selection)
                self.assertEqual(repeated.returncode, 0,
                                 repeated.stderr + repeated.stdout)
                self.assertIn("Verified satisfied: APL, BRN", repeated.stdout)
                self.assertIn("Executed: none", repeated.stdout)
                self.assertEqual({path: path.read_bytes() for path in tracked}, before)

    def test_pending_branch_can_be_completed_without_reextracting_zip(self):
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        before_history = self.history_path.read_bytes()
        resumed = self.invoke_zip("op=APPLY_PATCH", "skipApproves=true")
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        self.assertIn("GOAL STEP: BRN", resumed.stdout)
        self.assertNotIn("GOAL STEP: APL", resumed.stdout)
        self.assertNotEqual(self.history_path.read_bytes(), before_history)
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 1)

    def test_apply_patch_check_verifies_without_committing(self):
        stem = self.make_self_contained_zip()
        checked = self.invoke_zip("op=APPLY_PATCH_CHECK", "skipApproves=true",
                                  selection=stem)
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        self.assertIn("Executed: APL, BRN, CHK", checked.stdout)
        self.assertIn("MACRO APPLY_PATCH_CHECK: SUCCESS", checked.stdout)
        self.assertIn("final 10 [STS]", checked.stdout)
        self.assertEqual(next(iter(read_state_snapshot(self.state_path)["workflows"].values()))
                         ["phase"], "verified")
        self.assertEqual(command("git", "rev-parse", "HEAD",
                                 cwd=self.root).stdout.strip(), self.head)
        before_state = self.state_path.read_bytes()
        before_history = self.history_path.read_bytes()
        repeated = self.invoke_zip("op=APPLY_PATCH_CHECK", "skipApproves=true")
        self.assertEqual(repeated.returncode, 0, repeated.stderr + repeated.stdout)
        self.assertIn("Verified satisfied: APL, BRN, CHK", repeated.stdout)
        self.assertIn("Executed: none", repeated.stdout)
        self.assertEqual(self.state_path.read_bytes(), before_state)
        self.assertEqual(self.history_path.read_bytes(), before_history)

    def test_missing_check_blocks_before_application_and_shows_status(self):
        stem = self.make_self_contained_zip()
        self.project_config.write_text('schema_version: 1\nchecks:\n  - ["./missing-check.sh"]\n')
        result = self.invoke_zip("op=APPLY_PATCH_CHECK", "skipApproves=true",
                                 selection=stem)
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertIn("MISSING_CHECKS", result.stdout)
        self.assertIn("MACRO APPLY_PATCH_CHECK: STOPPED", result.stdout)
        self.assertIn("Executed: none", result.stdout)
        self.assertIn("final 10 [STS]", result.stdout)
        self.assertFalse(self.state_path.exists())
        self.assertFalse((self.root / "new.txt").exists())

    def test_failing_check_after_branch_transfer_retains_application_evidence(self):
        script = self.root / "run_checks.sh"
        script.write_text("#!/bin/sh\nset -eu\ntest -f new.txt\nexit 17\n")
        command("git", "add", "run_checks.sh", cwd=self.root)
        command("git", "commit", "-m", "Make canonical checks fail", cwd=self.root)
        command("git", "push", "origin", "main", cwd=self.root)
        self.head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.payload["base_commit"] = self.head
        stem = self.make_self_contained_zip()
        failed = self.invoke_zip("op=APPLY_PATCH_CHECK", "skipApproves=true",
                                 selection=stem)
        self.assertEqual(failed.returncode, 2, failed.stderr + failed.stdout)
        self.assertIn("MACRO APPLY_PATCH_CHECK: STOPPED", failed.stdout)
        self.assertIn("Executed: APL, BRN", failed.stdout)
        self.assertIn("Not executed: CHK", failed.stdout)
        self.assertIn("final 10 [STS]", failed.stdout)
        self.assertEqual(next(iter(read_state_snapshot(self.state_path)["workflows"].values()))
                         ["phase"], "patch_applied")
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 1)

    def test_wrong_checkout_blocks_without_branch_or_index_changes(self):
        stem = self.make_self_contained_zip()
        first = self.invoke_zip("op=APPLY_PATCH", "skipApproves=true", selection=stem)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        command("git", "switch", "main", cwd=self.root)
        before_index = (self.root / ".git/index").read_bytes()
        blocked = self.invoke_zip("op=APPLY_PATCH_CHECK", "skipApproves=true",
                                  selection=stem)
        self.assertEqual(blocked.returncode, 2, blocked.stderr + blocked.stdout)
        self.assertIn("MACRO APPLY_PATCH_CHECK: STOPPED", blocked.stdout)
        self.assertEqual((self.root / ".git/index").read_bytes(), before_index)

    def test_reserved_macro_names_do_not_change_numeric_action_contract(self):
        for name in ("APPLY_PATCH", "APPLY_PATCH_CHECK", "MERGE", "RUN_ALL"):
            self.assertEqual(parse_request([f"op={name.lower()}"]).op, name)
        for mode in ("--strict", "--force"):
            with self.subTest(mode=mode):
                result = self.invoke_zip("op=APPLY_PATCH", mode,
                                         "skipApproves=true", selection=None)
                self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
                self.assertIn("MACRO_MODE_UNSUPPORTED", result.stderr)
                self.assertIn("final 10 [STS]", result.stdout)
        for name in ("MERGE", "RUN_ALL"):
            with self.subTest(name=name):
                result = self.invoke_zip(f"op={name}", "skipApproves=true")
                self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
                self.assertNotIn("MACRO_NOT_IMPLEMENTED", result.stderr)
                self.assertIn("final 10 [STS]", result.stdout)
        self.assertFalse(self.state_path.exists())

    def test_macro_rejects_legacy_and_conflicting_lifecycle_args(self):
        stem = self.make_self_contained_zip()
        for options in (("op=APPLY_PATCH", "followup=true"),
                        ("op=APPLY_PATCH_CHECK", "handoffSeq=first.zip"),
                        ("op=MERGE", "opSeq=APL,CHK"),
                        ("opSeq=APPLY_PATCH",),
                        ("op=APPLY_PATCH", "patch=old.zip")):
            with self.subTest(options=options):
                result = self.invoke_zip(*options, selection=stem)
                self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertFalse(self.state_path.exists())

    def test_final_status_failure_does_not_mask_original_macro_error(self):
        request = parse_request(["op=APPLY_PATCH"])
        config = load_project_config(self.root, load_config(self.bin))
        with patch.object(macros, "resolve_handoffs", side_effect=Abort("original ZIP failure")):
            with patch.object(macros, "show_status_with_progress",
                              side_effect=Abort("unavailable STS")) as status:
                with self.assertRaisesRegex(Abort, "original ZIP failure"):
                    macros.execute_macro(request, self.root, config, self.bin)
                status.assert_called_once()

    def test_final_status_failure_does_not_turn_success_into_error(self):
        stem = self.make_self_contained_zip()
        request = parse_request([stem, "op=APPLY_PATCH", "skipApproves=true"])
        config = load_project_config(self.root, load_config(self.bin))
        with patch.object(macros, "show_status_with_progress",
                          side_effect=Abort("unavailable STS")) as status:
            macros.execute_macro(request, self.root, config, self.bin)
            status.assert_called_once()
        self.assertEqual(next(iter(read_state_snapshot(self.state_path)["workflows"].values()))
                         ["phase"], "patch_applied")

