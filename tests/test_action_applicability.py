"""AS-05: shared action applicability and conservative status recommendations."""

import unittest
from dataclasses import replace

from apatch_lib.action_applicability import (
    ActionFacts, PENDING_BRANCH_REASON, action_unavailable,
)
from apatch_lib.status import recommend_next_action
from tests._support import LocalGitFixture, command


class ApplicabilityMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strict = ActionFacts(
            mode="strict", phase="new", branch="main",
            planned_branch="feature/work", applied_branch="feature/work",
            base="main", clean=True, zip_selected=True)

    def test_strict_action_matrix_keeps_phase_and_branch_blockers(self) -> None:
        cases = (
            ("new", "main", 1, None),
            ("new", "main", 3, None),
            ("new", "elsewhere", 1, "requires current branch: main"),
            ("branch_created", "feature/work", 3, None),
            ("branch_created", "main", 3, None),
            ("patch_applied", "feature/work", 4, None),
            ("verified", "feature/work", 5, None),
            ("committed", "feature/work", 6, None),
            ("pushed", "feature/work", 7, None),
            ("pr_created", "feature/work", 8, None),
            ("merged", "feature/work", 9, None),
        )
        for phase, branch, number, expected in cases:
            with self.subTest(phase=phase, branch=branch, number=number):
                facts = replace(self.strict, phase=phase, branch=branch)
                self.assertEqual(action_unavailable(number, facts), expected)

    def test_strict_dirty_and_wrong_branch_do_not_bypass_policy(self) -> None:
        dirty = replace(self.strict, clean=False)
        self.assertEqual(action_unavailable(1, dirty), "requires a clean working tree")
        self.assertEqual(action_unavailable(3, dirty), "requires a clean working tree")
        wrong = replace(self.strict, phase="verified", branch="main")
        self.assertEqual(action_unavailable(5, wrong),
                         "requires current branch: feature/work")
        mismatched_application = replace(self.strict, phase="verified",
                                         branch="feature/work", applied_branch="main")
        self.assertIn("patch was applied to main",
                      action_unavailable(5, mismatched_application))

    def test_strict_require_feature_branch_allows_only_explicit_zip_first_exception(self) -> None:
        guarded = replace(self.strict, require_patch_feature_branch=True)
        self.assertIsNone(action_unavailable(3, guarded))
        legacy = replace(guarded, zip_selected=False)
        self.assertEqual(action_unavailable(3, legacy),
                         "requires current branch: feature/work")

    def test_pending_branch_blocks_every_action_except_transfer(self) -> None:
        for mode in ("loose", "strict", "force"):
            pending = replace(self.strict, mode=mode, phase="patch_applied",
                              zip_pending_branch=True, zip_first=True)
            with self.subTest(mode=mode):
                self.assertIsNone(action_unavailable(1, pending))
                for number in range(2, 10):
                    self.assertEqual(action_unavailable(number, pending),
                                     PENDING_BRANCH_REASON)

    def test_deprecated_bap_remains_blocked_in_each_mode(self) -> None:
        for mode in ("loose", "strict", "force"):
            facts = replace(self.strict, mode=mode, zip_first=True)
            self.assertIn("deprecated", action_unavailable(2, facts))

    def test_loose_force_keep_runtime_specific_recovery_guards(self) -> None:
        for mode in ("loose", "force"):
            manual = replace(self.strict, mode=mode, phase="verified",
                             branch="manual", clean=False)
            with self.subTest(mode=mode):
                for number in (3, 4, 5, 6, 7, 8, 9):
                    self.assertIsNone(action_unavailable(number, manual))

    def test_unknown_operation_is_not_treated_as_allowed(self) -> None:
        with self.assertRaises(ValueError):
            action_unavailable(99, self.strict)


class RecommendationMatrixTests(unittest.TestCase):
    def test_new_zip_first_and_legacy_selection_have_distinct_advice(self) -> None:
        for mode in ("loose", "strict", "force"):
            with self.subTest(mode=mode):
                number, alternative, _ = recommend_next_action(
                    "new", mode, "main", "feature/work",
                    base="main", zip_selected=True)
                self.assertEqual((number, alternative), (3, None))
        legacy, _, _ = recommend_next_action(
            "new", "strict", "main", "feature/work", base="main")
        self.assertEqual(legacy, 1)

    def test_conflict_dirty_zip_and_detached_checkout_do_not_suggest_apply(self) -> None:
        cases = (
            ("main", True, False),
            ("elsewhere", False, False),
            ("", False, False),
            ("main", False, True),
        )
        for branch, dirty, conflict in cases:
            with self.subTest(branch=branch, dirty=dirty, conflict=conflict):
                number, alternate, _ = recommend_next_action(
                    "new", "loose", branch, "feature/work",
                    base="main", dirty=dirty, conflict=conflict,
                    zip_selected=True)
                self.assertIsNone(number)
                self.assertIsNone(alternate)

    def test_strict_status_avoids_blocked_or_ambiguous_actions(self) -> None:
        cases = (
            ("branch_created", "main", 3),
            ("patch_applied", "main", 4),
            ("verified", "main", 5),
            ("committed", "main", 6),
            ("pushed", "main", 7),
            ("pr_created", "main", 8),
        )
        for phase, branch, action in cases:
            with self.subTest(phase=phase):
                number, alternate, _ = recommend_next_action(
                    phase, "strict", branch, "feature/work",
                    base="main", applied_branch="feature/work")
                self.assertIsNone(number, f"{phase} must not recommend {action}")
                self.assertIsNone(alternate)

    def test_stale_loose_verification_recommends_check_again(self) -> None:
        number, alternate, _ = recommend_next_action(
            "verified", "loose", "feature/work", "feature/work",
            stale_verification=True)
        self.assertEqual((number, alternate), (4, None))


class StatusAdviceCliTests(LocalGitFixture):
    def test_new_selected_zip_suggests_apl_without_creating_state(self) -> None:
        name = self.make_self_contained_zip()
        git_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout
        result = self.invoke_zip("op=STS", selection=name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Next suggested: 3 [APL]", result.stdout)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.lock_path.exists())
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout, git_head)

    def test_loose_manual_edit_invalidates_status_recommendation_not_saved_checks(self) -> None:
        name = self.make_self_contained_zip()
        self.assertEqual(self.invoke_zip("op=APL", "skipApproves=true",
                                         selection=name).returncode, 0)
        self.assertEqual(self.invoke_zip("op=BRN", "skipApproves=true").returncode, 0)
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        (self.root / "existing.txt").write_text("manually changed after verification\n")
        state_before = self.state_path.read_bytes()
        result = self.invoke_zip("op=STS")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Current verification: STALE [VERIFIED]", result.stdout)
        self.assertIn("Next suggested: 4 [CHK]", result.stdout)
        self.assertEqual(self.state_path.read_bytes(), state_before)

    def test_strict_manual_checkout_retains_legacy_apply_without_status_recommendation(self) -> None:
        created = self.invoke_cli("--strict", "op=BRN", "skipApproves=true")
        self.assertEqual(created.returncode, 0, created.stderr)
        command("git", "switch", "main", cwd=self.root)
        status = self.invoke_cli("--strict", "op=STS")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("Next suggested: NONE", status.stdout)
        allowed = self.invoke_cli("--strict", "op=APL", "skipApproves=true")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIn("RESULT 3 [APL]: SUCCESS", allowed.stdout)


if __name__ == "__main__":
    unittest.main()
