"""WM-05 guarded publication macros with local Git and mocked GitHub."""

from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest.mock import patch

from apatch_lib import github, macros
from apatch_lib.cli_request import parse_request
from apatch_lib.gitutil import head
from apatch_lib.handoff_selection import resolve_selected_handoff
from apatch_lib.model import Abort, RemoteOutcomeUnknown, load_config, load_project_config
from apatch_lib.planner import execute_goal
from apatch_lib.state import read_state_snapshot
from tests._support import LocalGitFixture, command
from tests.test_publication_goals import FakeGitHub


class RemoteMacroTests(LocalGitFixture):
    def config(self):
        return load_project_config(self.root, load_config(self.bin))

    def mocked_github(self, fake):
        return (patch.object(github, "repository", return_value="example/repo"),
                patch.object(github, "remote_repository", return_value="example/repo"),
                patch.object(github, "pr_list", side_effect=fake.listing),
                patch.object(github, "pr_details", side_effect=fake.details),
                patch.object(github, "gh_run", side_effect=fake.command))

    def run_macro(self, name, fake, *, stem=None, mode=None):
        args = ([stem] if stem else []) + [f"op={name}", "skipApproves=true"]
        if mode is not None:
            args.append(mode)
        request = parse_request(args)
        output = StringIO()
        try:
            with ExitStack() as stack:
                for stub in self.mocked_github(fake):
                    stack.enter_context(stub)
                stack.enter_context(redirect_stdout(output))
                macros.execute_macro(request, self.root, self.config(), self.bin)
        finally:
            self.last_output = output.getvalue()
        return self.last_output

    def prepare_goal(self, goal, fake, stem):
        selection = resolve_selected_handoff(stem, self.config(), self.root)
        with ExitStack() as stack:
            for stub in self.mocked_github(fake):
                stack.enter_context(stub)
            stack.enter_context(redirect_stdout(StringIO()))
            execute_goal(self.root, self.config(), self.bin, selection, goal=goal,
                         intent="auto", plan_only=False, skip_approves=True)

    def test_run_all_new_zip_completes_and_repeated_call_does_not_mutate(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        output = self.run_macro("RUN_ALL", fake, stem=stem)
        self.assertIn("MACRO PLAN RUN_ALL: APL, BRN, CHK, CMT, PSH, PR, MRG, SYN", output)
        self.assertIn("Executed: APL, BRN, CHK, CMT, PSH, PR, MRG, SYN", output)
        self.assertIn("MACRO RUN_ALL: SUCCESS", output)
        self.assertIn("final 10 [STS]", output)
        self.assertEqual(command("git", "branch", "--show-current",
                                 cwd=self.root).stdout.strip(), "main")
        self.assertEqual(next(iter(read_state_snapshot(self.state_path)["workflows"].values()))
                         ["phase"], "synced")
        self.assertEqual(fake.calls.count(("gh", "pr", "create")), 1)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)
        repeated = self.run_macro("RUN_ALL", fake)
        self.assertIn("MACRO RUN_ALL: SUCCESS", repeated)
        self.assertIn("Executed: none", repeated)
        self.assertEqual(fake.calls.count(("gh", "pr", "create")), 1)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)

    def test_merge_refuses_new_zip_before_application_or_remote_mutation(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        with self.assertRaisesRegex(Abort, "MERGE_SESSION_REQUIRED"):
            self.run_macro("MERGE", fake, stem=stem)
        self.assertIn("MACRO PLAN MERGE: BLOCKED", self.last_output)
        self.assertIn("MACRO MERGE: STOPPED", self.last_output)
        self.assertIn("final 10 [STS]", self.last_output)
        self.assertFalse(self.state_path.exists())
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual(fake.calls, [])

    def test_merge_from_checked_session_commits_and_publishes_exact_scope(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        self.run_macro("APPLY_PATCH_CHECK", fake, stem=stem)
        output = self.run_macro("MERGE", fake)
        self.assertIn("MACRO PLAN MERGE: CMT, PSH, PR, MRG, SYN", output)
        self.assertIn("Verified satisfied: APL, BRN, CHK", output)
        self.assertIn("Executed: CMT, PSH, PR, MRG, SYN", output)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)

    def test_merge_reuses_exact_open_pr_without_second_create(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        self.prepare_goal("PR_CREATED", fake, stem)
        output = self.run_macro("MERGE", fake)
        self.assertIn("MACRO PLAN MERGE: MRG, SYN", output)
        self.assertIn("Executed: MRG, SYN", output)
        self.assertEqual(fake.calls.count(("gh", "pr", "create")), 1)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)

    def test_unstable_github_checks_block_merge_without_relaxing_ci_policy(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        self.prepare_goal("PR_CREATED", fake, stem)
        original = fake.details

        def pending_details(*args, **kwargs):
            details = original(*args, **kwargs)
            details["mergeStateStatus"] = "UNSTABLE"
            details["statusCheckRollup"] = [{"name": "CI", "status": "IN_PROGRESS"}]
            return details

        fake.details = pending_details
        with self.assertRaisesRegex(Abort, "GitHub checks.*pending|UNSTABLE"):
            self.run_macro("MERGE", fake)
        self.assertIn("MACRO MERGE: STOPPED", self.last_output)
        self.assertIn("final 10 [STS]", self.last_output)
        self.assertNotIn(("gh", "pr", "merge"), fake.calls)

    def test_uncertain_pr_create_stops_then_reconciles_without_recreate(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        fake.unknown_create = True
        with self.assertRaises(RemoteOutcomeUnknown):
            self.run_macro("RUN_ALL", fake, stem=stem)
        self.assertIn("MACRO RUN_ALL: STOPPED", self.last_output)
        self.assertIn("final 10 [STS]", self.last_output)
        self.assertNotIn(("gh", "pr", "merge"), fake.calls)
        resumed = self.run_macro("RUN_ALL", fake)
        self.assertIn("MACRO RUN_ALL: SUCCESS", resumed)
        self.assertEqual(fake.calls.count(("gh", "pr", "create")), 1)

    def test_uncertain_merge_stops_then_reconciles_without_second_merge(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        self.prepare_goal("PR_CREATED", fake, stem)
        fake.unknown_merge = True
        with self.assertRaises(RemoteOutcomeUnknown):
            self.run_macro("MERGE", fake)
        self.assertIn("MACRO MERGE: STOPPED", self.last_output)
        self.assertIn("final 10 [STS]", self.last_output)
        resumed = self.run_macro("MERGE", fake)
        self.assertIn("MACRO MERGE: SUCCESS", resumed)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)

    def test_sync_failure_after_merge_resumes_only_sync(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        self.prepare_goal("PR_CREATED", fake, stem)

        def interrupted_sync(_config, root):
            command("git", "switch", "main", cwd=root)
            raise Abort("simulated sync interruption")

        with patch.object(github, "sync_local_base", side_effect=interrupted_sync):
            with self.assertRaisesRegex(Abort, "simulated sync interruption"):
                self.run_macro("MERGE", fake)
        resumed = self.run_macro("MERGE", fake)
        self.assertIn("MACRO PLAN MERGE: SYN", resumed)
        self.assertIn("Executed: SYN", resumed)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)

    def test_unclassified_manual_edit_blocks_publication(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        self.prepare_goal("COMMITTED", fake, stem)
        (self.root / "manual.txt").write_text("manual change\n")
        with self.assertRaisesRegex(Abort, "PUBLICATION_DIRTY_WORKTREE"):
            self.run_macro("MERGE", fake)
        self.assertNotIn(("gh", "pr", "create"), fake.calls)
        self.assertNotIn(("gh", "pr", "merge"), fake.calls)

    def test_run_all_preserves_failed_checks_and_never_publishes(self):
        script = self.root / "run_checks.sh"
        script.write_text("#!/bin/sh\nset -eu\ntest -f new.txt\nexit 19\n")
        command("git", "add", "run_checks.sh", cwd=self.root)
        command("git", "commit", "-m", "Make project checks fail", cwd=self.root)
        command("git", "push", "origin", "main", cwd=self.root)
        self.payload["base_commit"] = head(self.root)
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        with self.assertRaisesRegex(Abort, r"Command failed \(19\)"):
            self.run_macro("RUN_ALL", fake, stem=stem)
        self.assertIn("Executed: APL, BRN", self.last_output)
        self.assertIn("Not executed: CHK", self.last_output)
        self.assertEqual(fake.calls, [])
        self.assertEqual(next(iter(read_state_snapshot(self.state_path)["workflows"].values()))
                         ["phase"], "patch_applied")

    def test_run_all_uses_explicit_macro_prepare_before_checks(self):
        prepare = self.root / "prepare.sh"
        prepare.write_text("#!/bin/sh\nset -eu\nprintf 'prepared\\n' > existing.txt\n")
        prepare.chmod(0o755)
        checks = self.root / "run_checks.sh"
        checks.write_text("#!/bin/sh\nset -eu\ntest -f new.txt\n"
                          "grep -q '^prepared$' existing.txt\n")
        self.project_config.write_text(
            'schema_version: 1\ncheck_worktree_policy: recheck_once\n'
            'prepare_checks:\n  - ["./prepare.sh"]\n'
            'checks:\n  - ["./run_checks.sh"]\n')
        command("git", "add", "-A", cwd=self.root)
        command("git", "commit", "-m", "Prepare before macro checks", cwd=self.root)
        command("git", "push", "origin", "main", cwd=self.root)
        self.payload["base_commit"] = head(self.root)
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        output = self.run_macro("RUN_ALL", fake, stem=stem)
        self.assertIn("PREPARE 1/1", output)
        self.assertIn("MACRO RUN_ALL: SUCCESS", output)
        self.assertEqual((self.root / "existing.txt").read_text(), "prepared\n")

    def test_completed_merge_with_unfinished_session_finalizes_without_remerge(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        self.prepare_goal("PR_CREATED", fake, stem)
        with patch("apatch_lib.planner._complete_merged_session",
                   side_effect=Abort("interrupted session finalization")):
            with self.assertRaisesRegex(Abort, "interrupted session finalization"):
                self.run_macro("MERGE", fake)
        output = self.run_macro("MERGE", fake)
        self.assertIn("MACRO PLAN MERGE: FIN", output)
        self.assertIn("Executed: FIN", output)
        self.assertIn("MACRO MERGE: SUCCESS", output)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)

    def test_new_zip_after_completed_merge_starts_independent_session(self):
        first = self.make_self_contained_zip()
        initial = FakeGitHub(self)
        self.run_macro("RUN_ALL", initial, stem=first)
        self.payload["feature_branch"] = "feature/test-second-session"
        self.payload["base_commit"] = head(self.root)
        second = self.make_followup_zip(
            filename="example_service-PATCH-2026-10-29-20-00-second.zip")
        fake = FakeGitHub(self)
        output = self.run_macro("RUN_ALL", fake, stem=second.stem)
        self.assertIn("MACRO PLAN RUN_ALL: APL, BRN, CHK, CMT, PSH, PR, MRG, SYN", output)
        self.assertIn("MACRO RUN_ALL: SUCCESS", output)
        state = read_state_snapshot(self.state_path)
        self.assertEqual(len(state["feature_sessions"]), 2)
        self.assertEqual({item["status"] for item in state["feature_sessions"].values()},
                         {"merged"})
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)

    def test_remote_macros_reject_strict_and_force_before_mutation(self):
        stem = self.make_self_contained_zip()
        fake = FakeGitHub(self)
        for mode in ("--strict", "--force"):
            for name in ("MERGE", "RUN_ALL"):
                with self.subTest(mode=mode, name=name):
                    with self.assertRaisesRegex(Abort, "MACRO_MODE_UNSUPPORTED"):
                        self.run_macro(name, fake, stem=stem, mode=mode)
                    self.assertIn("final 10 [STS]", self.last_output)
        self.assertFalse(self.state_path.exists())
        self.assertEqual(fake.calls, [])
