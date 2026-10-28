"""Guarded remote-goal regressions with local bare Git and mocked GitHub."""

from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest.mock import patch

from apatch_lib import github
from apatch_lib.gitutil import head
from apatch_lib.handoff_selection import resolve_selected_handoff
from apatch_lib.model import Abort, RemoteOutcomeUnknown, load_config, load_project_config
from apatch_lib.planner import build_plan, execute_goal
from apatch_lib.state import read_state_snapshot
from tests._support import LocalGitFixture, command


class FakeGitHub:
    """Stand-in for only the GitHub PR observations and mutations used by goals."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.state = None
        self.number = 37
        self.sha = None
        self.calls = []
        self.unknown_create = False
        self.unknown_merge = False

    def listing(self, *_args, **_kwargs):
        return [self.details()] if self.state else []

    def details(self, *_args, **_kwargs):
        if self.state is None:
            raise Abort("No matching PR")
        return {
            "number": self.number, "state": self.state,
            "headRefName": self.fixture.payload["feature_branch"],
            "baseRefName": "main", "headRefOid": self.sha,
            "url": f"https://github.com/example/repo/pull/{self.number}",
            "reviewDecision": "APPROVED", "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"name": "test", "conclusion": "SUCCESS"}],
            "mergedAt": "2026-10-28T17:00:00Z" if self.state == "MERGED" else None,
            "mergeCommit": {"oid": self.sha} if self.state == "MERGED" else None,
        }

    def command(self, _config, _root, argv):
        self.calls.append(tuple(argv[:3]))
        if argv[:3] == ["gh", "pr", "create"]:
            self.sha = head(self.fixture.root)
            self.state = "OPEN"
            if self.unknown_create:
                self.unknown_create = False
                raise RemoteOutcomeUnknown("Create command returned an unknown result")
        elif argv[:3] == ["gh", "pr", "merge"]:
            self.state = "MERGED"
            command("git", "--git-dir", str(self.fixture.remote), "update-ref",
                    "refs/heads/main", self.sha, cwd=self.fixture.base)
            if self.unknown_merge:
                self.unknown_merge = False
                raise RemoteOutcomeUnknown("Merge command returned an unknown result")


class PublicationGoalTests(LocalGitFixture):
    def setup_goal(self):
        name = self.make_self_contained_zip()
        config = load_project_config(self.root, load_config(self.bin))
        selected = resolve_selected_handoff(name, config, self.root)
        return config, selected

    def goal(self, config, selected, name, *, preview=False):
        console = StringIO()
        with redirect_stdout(console):
            execute_goal(self.root, config, self.bin, selected, goal=name,
                         intent="auto", plan_only=preview, skip_approves=True)
        return console.getvalue()

    def mocked_github(self, fake):
        return (patch.object(github, "repository", return_value="example/repo"),
                patch.object(github, "remote_repository", return_value="example/repo"),
                patch.object(github, "pr_list", side_effect=fake.listing),
                patch.object(github, "pr_details", side_effect=fake.details),
                patch.object(github, "gh_run", side_effect=fake.command))

    def run_with_fake(self, fake, config, selected, goal):
        patches = self.mocked_github(fake)
        for item in patches:
            item.start()
        try:
            return self.goal(config, selected, goal)
        finally:
            for item in reversed(patches):
                item.stop()

    def test_pushed_goal_uses_exact_guarded_commit_and_fast_forward_remote(self):
        config, selected = self.setup_goal()
        preview = build_plan(self.root, config, selected, "PUSHED")
        self.assertEqual(preview.steps, ("APL", "BRN", "CHK", "CMT", "PSH"))
        result = self.goal(config, selected, "PUSHED")
        self.assertIn("GOAL PUSHED: SUCCESS", result)
        published = head(self.root)
        self.assertEqual(command("git", "ls-remote", "--heads", "origin",
                                 f"refs/heads/{self.payload['feature_branch']}",
                                 cwd=self.root).stdout.split()[0], published)
        state = read_state_snapshot(self.state_path)
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "pushed")
        self.assertIn(published, next(iter(state["feature_sessions"].values()))["commit_shas"])
        self.assertIn("ALREADY_SATISFIED", self.goal(config, selected, "PUSHED"))

    def test_new_zip_after_pushed_commit_continues_same_session(self):
        config, first = self.setup_goal()
        self.goal(config, first, "PUSHED")
        prior_head = head(self.root)
        followup = self.make_followup_zip()
        selected = resolve_selected_handoff(followup.stem, config, self.root)
        preview = build_plan(self.root, config, selected, "PUSHED", "continue")
        self.assertEqual(preview.steps, ("APL", "CHK", "CMT", "PSH"))
        self.assertFalse(preview.blockers)
        output = StringIO()
        with redirect_stdout(output):
            execute_goal(self.root, config, self.bin, selected, goal="PUSHED",
                         intent="continue", plan_only=False, skip_approves=True)
        self.assertIn("GOAL PUSHED: SUCCESS", output.getvalue())
        self.assertNotEqual(head(self.root), prior_head)
        state = read_state_snapshot(self.state_path)
        session = next(iter(state["feature_sessions"].values()))
        self.assertEqual(len(session["patch_workflow_keys"]), 2)
        self.assertEqual(len(session["commit_shas"]), 2)

    def test_merged_goal_separates_remote_merge_from_base_sync(self):
        config, selected = self.setup_goal()
        fake = FakeGitHub(self)
        initial = build_plan(self.root, config, selected, "MERGED")
        self.assertEqual(initial.steps,
                         ("APL", "BRN", "CHK", "CMT", "PSH", "PR", "MRG", "SYN"))
        result = self.run_with_fake(fake, config, selected, "MERGED")
        self.assertIn("GOAL STEP: MRG", result)
        self.assertIn("GOAL STEP: SYN", result)
        self.assertIn("GOAL MERGED: SUCCESS", result)
        self.assertEqual(command("git", "branch", "--show-current",
                                 cwd=self.root).stdout.strip(), "main")
        state = read_state_snapshot(self.state_path)
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "synced")
        session = next(iter(state["feature_sessions"].values()))
        self.assertEqual(session["status"], "merged")
        self.assertEqual([(item["number"], item["state"]) for item in session["pr_revisions"]],
                         [(37, "OPEN"), (37, "MERGED")])
        self.assertIn("ALREADY_SATISFIED",
                      self.run_with_fake(fake, config, selected, "MERGED"))
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)

    def test_stale_pr_head_blocks_merge_before_mutation(self):
        config, selected = self.setup_goal()
        fake = FakeGitHub(self)
        self.run_with_fake(fake, config, selected, "PR_CREATED")
        fake.sha = "b" * 40
        with self.assertRaisesRegex(Abort, "PR"):
            self.run_with_fake(fake, config, selected, "MERGED")
        self.assertNotIn(("gh", "pr", "merge"), fake.calls)

    def test_previously_merged_exact_pr_is_adopted_without_merge_command(self):
        config, selected = self.setup_goal()
        fake = FakeGitHub(self)
        self.run_with_fake(fake, config, selected, "PR_CREATED")
        fake.state = "MERGED"
        command("git", "--git-dir", str(self.remote), "update-ref",
                "refs/heads/main", fake.sha, cwd=self.base)
        result = self.run_with_fake(fake, config, selected, "MERGED")
        self.assertIn("GOAL MERGED: SUCCESS", result)
        self.assertIn("GOAL STEP: SYN", result)
        self.assertNotIn(("gh", "pr", "merge"), fake.calls)

    def test_unclassified_manual_changes_block_publication(self):
        config, selected = self.setup_goal()
        self.goal(config, selected, "COMMITTED")
        (self.root / "manual.txt").write_text("developer owned\n")
        with self.assertRaisesRegex(Abort, "PUBLICATION_DIRTY_WORKTREE"):
            self.goal(config, selected, "PUSHED")
        self.assertFalse(command(
            "git", "ls-remote", "--heads", "origin",
            f"refs/heads/{self.payload['feature_branch']}",
            cwd=self.root).stdout)

    def test_unknown_pr_creation_adopts_exact_open_pr_without_recreating(self):
        config, selected = self.setup_goal()
        fake = FakeGitHub(self)
        fake.unknown_create = True
        with self.assertRaises(RemoteOutcomeUnknown):
            self.run_with_fake(fake, config, selected, "PR_CREATED")
        result = self.run_with_fake(fake, config, selected, "PR_CREATED")
        self.assertIn("remote outcome reconciled read-only", result)
        self.assertIn("GOAL PR_CREATED: SUCCESS", result)
        self.assertEqual(fake.calls.count(("gh", "pr", "create")), 1)

    def test_unknown_merge_adopts_verified_merge_then_syncs_once(self):
        config, selected = self.setup_goal()
        fake = FakeGitHub(self)
        self.run_with_fake(fake, config, selected, "PR_CREATED")
        fake.unknown_merge = True
        with self.assertRaises(RemoteOutcomeUnknown):
            self.run_with_fake(fake, config, selected, "MERGED")
        result = self.run_with_fake(fake, config, selected, "MERGED")
        self.assertIn("remote outcome reconciled read-only", result)
        self.assertIn("GOAL MERGED: SUCCESS", result)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)

    def test_sync_failure_after_switching_base_resumes_without_second_merge(self):
        config, selected = self.setup_goal()
        fake = FakeGitHub(self)
        self.run_with_fake(fake, config, selected, "PR_CREATED")

        def interrupted_sync(_config, root):
            command("git", "switch", "main", cwd=root)
            raise Abort("simulated sync interruption after branch switch")

        with patch.object(github, "sync_local_base", side_effect=interrupted_sync):
            with self.assertRaisesRegex(Abort, "simulated sync interruption"):
                self.run_with_fake(fake, config, selected, "MERGED")
        state = read_state_snapshot(self.state_path)
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "merged")
        self.assertEqual(command("git", "branch", "--show-current",
                                 cwd=self.root).stdout.strip(), "main")
        resumed = self.run_with_fake(fake, config, selected, "MERGED")
        self.assertIn("GOAL STEP: SYN", resumed)
        self.assertNotIn("GOAL STEP: MRG", resumed)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)
        self.assertIn("GOAL MERGED: SUCCESS", resumed)

    def test_completed_sync_with_interrupted_session_finalization_resumes_locally(self):
        config, selected = self.setup_goal()
        fake = FakeGitHub(self)
        self.run_with_fake(fake, config, selected, "PR_CREATED")
        with patch("apatch_lib.planner._complete_merged_session",
                   side_effect=Abort("simulated interrupted session finalization")):
            with self.assertRaisesRegex(Abort, "simulated interrupted session finalization"):
                self.run_with_fake(fake, config, selected, "MERGED")
        state = read_state_snapshot(self.state_path)
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "synced")
        self.assertEqual(next(iter(state["feature_sessions"].values()))["status"], "active")
        with ExitStack() as stack:
            for stub in self.mocked_github(fake):
                stack.enter_context(stub)
            plan = build_plan(self.root, config, selected, "MERGED")
        self.assertFalse(plan.blockers, plan.blockers)
        self.assertEqual(plan.steps, ("FIN",))
        resumed = self.run_with_fake(fake, config, selected, "MERGED")
        self.assertIn("GOAL STEP: FIN", resumed)
        self.assertIn("GOAL MERGED: SUCCESS", resumed)
        self.assertEqual(fake.calls.count(("gh", "pr", "merge")), 1)
        self.assertEqual(next(iter(read_state_snapshot(self.state_path)["feature_sessions"].values()))
                         ["status"], "merged")

    def test_unknown_create_without_live_pr_never_reissues_mutation(self):
        config, selected = self.setup_goal()
        fake = FakeGitHub(self)
        fake.unknown_create = True
        with self.assertRaises(RemoteOutcomeUnknown):
            self.run_with_fake(fake, config, selected, "PR_CREATED")
        fake.state = None
        with self.assertRaisesRegex(Abort, "UNKNOWN_REMOTE_RESULT"):
            self.run_with_fake(fake, config, selected, "PR_CREATED")
        self.assertEqual(fake.calls.count(("gh", "pr", "create")), 1)
