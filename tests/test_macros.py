"""WM-03 local macro dispatch and best-effort terminal status regressions."""

from unittest.mock import patch

from apatch_lib import macros
from apatch_lib.cli_request import parse_request
from apatch_lib.model import Abort, load_config, load_project_config
from apatch_lib.patch_history import AppliedPatchHistory
from apatch_lib.state import read_state_snapshot
from tests._support import LocalGitFixture, command


class LocalMacroTests(LocalGitFixture):
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
                self.assertIn("MACRO_NOT_IMPLEMENTED", result.stderr)
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
