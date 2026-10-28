"""Regression tests for github contracts."""

import time

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


class GithubGuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.branch = "feature/a"
        self.sha = "a" * 40
        from apatch_lib.model import Config, Handoff
        self.config = Config(self.root, self.root / "state.json", self.root / "logs", self.root / "history.txt", "origin", "main",
                             (("./run_checks.sh",),), True, True, "merge", 10000)
        self.handoff = Handoff("example_service", self.branch, "patch.zip", "test: message\n", None, None, ())
        self.record = {"phase": "pr_created", "pushed_sha": self.sha, "pr_number": 4}
        self.details = {"number": 4, "state": "OPEN", "headRefName": self.branch,
                        "baseRefName": "main", "headRefOid": self.sha,
                        "url": "https://github.com/example/repo/pull/4", "reviewDecision": "APPROVED",
                        "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
                        "statusCheckRollup": [{"name": "test", "conclusion": "SUCCESS"}], "mergedAt": None}

    def test_pr_creation_targets_the_project_base_and_rejects_another_target(self):
        from apatch_lib import github

        config = replace(self.config, base="release/2026-q4", base_branch_source="project")
        self.record["pushed_sha"] = self.sha
        expected = dict(self.details, baseRefName="release/2026-q4")
        with patch.object(github, "require_clean"), \
             patch.object(github, "head", return_value=self.sha), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", side_effect=[[], [expected]]), \
             patch.object(github, "confirm", return_value=True), \
             patch.object(github, "gh_run") as mutate:
            github.create_pr(config, self.handoff, self.root, self.record, lambda: None)
        argv = mutate.call_args.args[2]
        self.assertEqual(argv[argv.index("--base") + 1], "release/2026-q4")
        self.assertEqual(self.record["pr_number"], 4)

        self.record.pop("pr_number", None)
        with patch.object(github, "require_clean"), \
             patch.object(github, "head", return_value=self.sha), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[dict(self.details)]), \
             patch.object(github, "gh_run") as mutate:
            with self.assertRaisesRegex(Abort, "another base branch"):
                github.create_pr(config, self.handoff, self.root, self.record, lambda: None)
            mutate.assert_not_called()

    def test_mutating_github_transport_timeout_is_unknown_and_never_retried(self):
        from apatch_lib import github

        for operation in ("create", "merge"):
            with self.subTest(operation=operation), \
                    patch.object(github, "run", side_effect=Abort("Post API: i/o timeout")) as runner:
                with self.assertRaises(RemoteOutcomeUnknown) as captured:
                    github.gh_run(self.config, self.root, ["gh", "pr", operation, "--repo", "example/repo"])
                self.assertIn("result is unknown", str(captured.exception))
                self.assertIn("no automatic retry", str(captured.exception))
                runner.assert_called_once()

        with patch.object(github, "run", side_effect=Abort("GraphQL permission denied")) as runner:
            with self.assertRaises(Abort) as captured:
                github.gh_run(self.config, self.root, ["gh", "pr", "merge", "4"])
            self.assertNotIsInstance(captured.exception, RemoteOutcomeUnknown)
            runner.assert_called_once()

    def run_guard(self, *, approval=None, check=None, sha=None):
        from unittest.mock import patch
        from apatch_lib import github
        payload = dict(self.details)
        if approval is not None:
            payload["reviewDecision"] = approval
        if check is not None:
            payload["statusCheckRollup"] = [{"name": "test", "conclusion": check}]
        if sha is not None:
            payload["headRefOid"] = sha
        with patch.object(github, "require_clean"), patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[dict(self.details)]), \
             patch.object(github, "pr_details", return_value=payload), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "run") as fake_run, \
             patch.object(github, "confirm", return_value=True):
            try:
                github.merge_pr(self.config, self.handoff, self.root, self.record, lambda: None)
            except Abort as error:
                self.assertFalse(any("merge" in str(call) for call in fake_run.call_args_list))
                return str(error)
        raise AssertionError("Expected merge to be rejected")

    def test_pending_check_blocks_merge(self):
        self.assertIn("pending checks", self.run_guard(check="PENDING"))

    def test_no_published_ci_blocks_merge_by_default(self):
        self.details["statusCheckRollup"] = []
        self.assertIn("no published checks", self.run_guard())

    def test_missing_approval_blocks_merge(self):
        self.assertIn("not approved", self.run_guard(approval="REVIEW_REQUIRED"))

    def test_project_override_does_not_skip_pending_ci(self):
        self.config = replace(self.config, require_approval=False, review_approval_source="project")
        self.assertIn("pending checks", self.run_guard(approval="REVIEW_REQUIRED", check="PENDING"))

    def test_project_override_does_not_skip_stale_pr_head(self):
        self.config = replace(self.config, require_approval=False, review_approval_source="project")
        self.assertIn("drifted", self.run_guard(approval="REVIEW_REQUIRED", sha="b" * 40))

    def test_project_override_allows_clean_pr_without_approval(self):
        from apatch_lib import github
        self.config = replace(self.config, require_approval=False, review_approval_source="project")
        pending_review = dict(self.details, reviewDecision="REVIEW_REQUIRED")
        after = dict(pending_review, state="MERGED", mergedAt="2026-10-23T14:00:00Z")
        console = StringIO()
        with patch.object(github, "require_clean"), patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[dict(self.details)]), \
             patch.object(github, "pr_details", side_effect=[pending_review, after]), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "run") as fake_run, \
             patch.object(github, "confirm", return_value=True), redirect_stdout(console):
            github.merge_pr(self.config, self.handoff, self.root, self.record, lambda: None)
        self.assertIn("PR review approval: not required (source: project)", console.getvalue())
        self.assertIn("PR CI checks: required (source: global)", console.getvalue())
        self.assertEqual(self.record["phase"], "merged")
        self.assertTrue(any(call.args[0][:3] == ["gh", "pr", "merge"] for call in fake_run.call_args_list))

    def test_ci_opt_out_allows_no_published_checks_without_skipping_review_or_identity(self):
        from apatch_lib import github
        self.config = replace(self.config, require_checks=False, required_checks_source="project")
        initial = dict(self.details, statusCheckRollup=[])
        after = dict(initial, state="MERGED", mergedAt="2026-10-24T00:00:00Z")
        console = StringIO()
        with patch.object(github, "require_clean"), patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[dict(self.details)]), \
             patch.object(github, "pr_details", side_effect=[initial, after]), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "run") as fake_run, \
             patch.object(github, "confirm", return_value=True), redirect_stdout(console):
            github.merge_pr(self.config, self.handoff, self.root, self.record, lambda: None)
        self.assertIn("PR review approval: required (source: global)", console.getvalue())
        self.assertIn("PR CI checks: not required (source: project)", console.getvalue())
        self.assertEqual(self.record["phase"], "merged")
        self.assertTrue(any(call.args[0][:3] == ["gh", "pr", "merge"] for call in fake_run.call_args_list))
        self.assertFalse(any(call.args[0][:3] == ["gh", "pr", "checks"] for call in fake_run.call_args_list))

    def test_ci_opt_out_does_not_skip_required_review(self):
        self.config = replace(self.config, require_checks=False, required_checks_source="project")
        self.details["statusCheckRollup"] = []
        self.assertIn("not approved", self.run_guard(approval="REVIEW_REQUIRED"))

    def test_both_opt_outs_still_reject_drift(self):
        self.config = replace(self.config, require_checks=False, required_checks_source="project",
                              require_approval=False, review_approval_source="project")
        self.details["statusCheckRollup"] = []
        self.assertIn("drifted", self.run_guard(approval="REVIEW_REQUIRED", sha="b" * 40))

    def test_project_override_does_not_bypass_github_merge_rejection(self):
        from apatch_lib import github
        self.config = replace(self.config, require_approval=False, review_approval_source="project",
                              require_checks=False, required_checks_source="project")
        pending_review = dict(self.details, reviewDecision="REVIEW_REQUIRED", statusCheckRollup=[])

        def gh_command(_config, _root, argv):
            if argv[:3] == ["gh", "pr", "merge"]:
                raise Abort("GitHub repository policy rejected merge")

        with patch.object(github, "require_clean"), patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[dict(self.details)]), \
             patch.object(github, "pr_details", return_value=pending_review), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "gh_run", side_effect=gh_command), \
             patch.object(github, "confirm", return_value=True):
            with self.assertRaisesRegex(Abort, "GitHub repository policy rejected merge"):
                github.merge_pr(self.config, self.handoff, self.root, self.record, lambda: None)
        self.assertEqual(self.record["phase"], "pr_created")

    def test_pr_head_drift_blocks_merge(self):
        self.assertIn("drifted", self.run_guard(sha="b" * 40))

    def test_clean_approved_pr_permits_guarded_merge(self):
        from unittest.mock import patch
        from apatch_lib import github
        after = dict(self.details, state="MERGED", mergedAt="2026-10-22T10:00:00Z")
        with patch.object(github, "require_clean"), patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[dict(self.details)]), \
             patch.object(github, "pr_details", side_effect=[dict(self.details), after]), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "run") as fake_run, \
             patch.object(github, "confirm", return_value=True):
            github.merge_pr(self.config, self.handoff, self.root, self.record, lambda: None)
        self.assertEqual(self.record["phase"], "merged")
        self.assertTrue(any(call.args[0][:3] == ["gh", "pr", "merge"] for call in fake_run.call_args_list))

    def test_new_pr_created_without_attempting_merge(self):
        from unittest.mock import patch
        from apatch_lib import github
        record = {"phase": "pushed", "pushed_sha": self.sha}
        created = {"number": 4, "state": "OPEN", "headRefName": self.branch,
                   "baseRefName": "main", "headRefOid": self.sha, "url": self.details["url"]}
        with patch.object(github, "require_clean"), patch.object(github, "head", return_value=self.sha), \
             patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", side_effect=[[], [created]]), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "output", return_value="[]"), \
             patch.object(github, "run") as fake_run, \
             patch.object(github, "confirm", return_value=True):
            github.create_pr(self.config, self.handoff, self.root, record, lambda: None)
        self.assertEqual(record["phase"], "pr_created")
        self.assertEqual(record["pr_number"], 4)
        self.assertTrue(any(call.args[0][:3] == ["gh", "pr", "create"] for call in fake_run.call_args_list))
        self.assertFalse(any(call.args[0][:3] == ["gh", "pr", "merge"] for call in fake_run.call_args_list))

    def test_pr_creation_uses_one_initial_listing_including_other_bases(self):
        from apatch_lib import github
        record = {"phase": "pushed", "pushed_sha": self.sha}
        created = dict(self.details)
        with patch.object(github, "require_clean"), patch.object(github, "head", return_value=self.sha), \
             patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "gh_output", side_effect=["[]", json.dumps([created])]) as listing, \
             patch.object(github, "gh_run") as execute, patch.object(github, "confirm", return_value=True):
            github.create_pr(self.config, self.handoff, self.root, record, lambda: None)
        self.assertEqual(record["pr_number"], created["number"])
        self.assertEqual(listing.call_count, 2)
        for listing_call in listing.call_args_list:
            args = listing_call.args[2]
            self.assertEqual(args[:3], ["gh", "pr", "list"])
            self.assertEqual(args[args.index("--state") + 1], "all")
            self.assertIn("--limit", args)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[2][:3], ["gh", "pr", "create"])

    def test_existing_matching_pr_is_adopted_without_creation(self):
        from apatch_lib import github
        record = {"phase": "pushed", "pushed_sha": self.sha}
        with patch.object(github, "require_clean"), patch.object(github, "head", return_value=self.sha), \
             patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "gh_output", return_value=json.dumps([self.details])) as listing, \
             patch.object(github, "gh_run") as execute, patch.object(github, "confirm") as approval:
            github.create_pr(self.config, self.handoff, self.root, record, lambda: None)
        self.assertEqual(record["phase"], "pr_created")
        self.assertEqual(record["pr_number"], self.details["number"])
        listing.assert_called_once()
        execute.assert_not_called()
        approval.assert_not_called()

    def test_open_pr_with_different_base_blocks_creation_without_second_lookup(self):
        from apatch_lib import github
        wrong_base = dict(self.details, baseRefName="develop")
        record = {"phase": "pushed", "pushed_sha": self.sha}
        with patch.object(github, "require_clean"), patch.object(github, "head", return_value=self.sha), \
             patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "gh_output", return_value=json.dumps([wrong_base])) as listing, \
             patch.object(github, "gh_run") as execute:
            with self.assertRaisesRegex(Abort, "another base"):
                github.create_pr(self.config, self.handoff, self.root, record, lambda: None)
        listing.assert_called_once()
        execute.assert_not_called()
        self.assertEqual(record["phase"], "pushed")

    def test_pr_create_timeout_can_be_reconciled_on_next_run_without_duplicate(self):
        from apatch_lib import github
        record = {"phase": "pushed", "pushed_sha": self.sha}
        persist = []
        with patch.object(github, "require_clean"), patch.object(github, "head", return_value=self.sha), \
             patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "gh_output", side_effect=["[]", json.dumps([self.details])]) as listing, \
             patch.object(github, "gh_run", side_effect=Abort("GitHub command timed out")) as execute, \
             patch.object(github, "confirm", return_value=True):
            with self.assertRaisesRegex(Abort, "timed out"):
                github.create_pr(self.config, self.handoff, self.root, record,
                                 lambda: persist.append(dict(record)))
            self.assertEqual(record["phase"], "pushed")
            self.assertEqual(persist, [])
            github.create_pr(self.config, self.handoff, self.root, record,
                             lambda: persist.append(dict(record)))
        self.assertEqual(record["phase"], "pr_created")
        self.assertEqual(record["pr_number"], self.details["number"])
        self.assertEqual(len(persist), 1)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(listing.call_count, 2)

    def test_pr_create_verification_timeout_after_mutation_is_unknown(self):
        from apatch_lib import github

        record = {"phase": "pushed", "pushed_sha": self.sha}
        with patch.object(github, "require_clean"), patch.object(github, "head", return_value=self.sha), \
                patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "remote_head", return_value=self.sha), \
                patch.object(github, "pr_list", side_effect=[[], Abort("GitHub timeout")]), \
                patch.object(github, "gh_run") as mutation, \
                patch.object(github, "confirm", return_value=True):
            with self.assertRaises(RemoteOutcomeUnknown) as result:
                github.create_pr(self.config, self.handoff, self.root, record, lambda: None)
        mutation.assert_called_once()
        self.assertIn("verification was unavailable", str(result.exception))
        self.assertEqual(record["phase"], "pushed")

    def test_pr_merge_confirmation_timeout_after_mutation_is_unknown(self):
        from apatch_lib import github

        record = dict(self.record)
        with patch.object(github, "require_clean"), \
                patch.object(github, "verified_repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[self.details]), \
                patch.object(github, "pr_details", side_effect=[self.details, Abort("GitHub timeout")]), \
                patch.object(github, "remote_head", return_value=self.sha), \
                patch.object(github, "gh_run") as mutation, \
                patch.object(github, "confirm", return_value=True):
            with self.assertRaises(RemoteOutcomeUnknown) as result:
                github.merge_pr(self.config, self.handoff, self.root, record, lambda: None,
                                verified_repo="example/repo")
        self.assertEqual(sum(call.args[2][:3] == ["gh", "pr", "merge"]
                             for call in mutation.call_args_list), 1)
        self.assertIn("confirmation was unavailable", str(result.exception))
        self.assertEqual(record["phase"], "pr_created")

    def test_new_pr_can_follow_historical_merged_pr_on_same_branch(self):
        from apatch_lib import github

        old_pr = dict(self.details, number=5, state="MERGED", headRefOid="b" * 40)
        current_pr = dict(self.details, number=6, state="OPEN")
        record = {"phase": "synced", "pr_number": 5, "pushed_sha": self.sha,
                  "local_base_head": "c" * 40}
        with patch.object(github, "require_clean"), patch.object(github, "head", return_value=self.sha), \
                patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "remote_head", return_value=self.sha), \
                patch.object(github, "pr_list", side_effect=[[old_pr], [old_pr, current_pr]]), \
                patch.object(github, "gh_run") as execute, \
                patch.object(github, "confirm", return_value=True):
            github.create_pr(self.config, self.handoff, self.root, record, lambda: None)
        self.assertEqual(record["phase"], "pr_created")
        self.assertEqual(record["pr_number"], 6)
        self.assertNotIn("local_base_head", record)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[2][:3], ["gh", "pr", "create"])

    def test_merge_ignores_historical_merged_pr_but_uses_recorded_open_pr(self):
        from apatch_lib import github

        old_pr = dict(self.details, number=5, state="MERGED", headRefOid="b" * 40)
        current_pr = dict(self.details, number=6, state="OPEN")
        merged = dict(current_pr, state="MERGED", mergedAt="2026-10-24T06:23:48Z")
        record = dict(self.record, pr_number=6)
        with patch.object(github, "require_clean"), \
                patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[old_pr, current_pr]), \
                patch.object(github, "pr_details", side_effect=[current_pr, merged]), \
                patch.object(github, "remote_head", return_value=self.sha), \
                patch.object(github, "gh_run") as execute, \
                patch.object(github, "confirm", return_value=True):
            github.merge_pr(self.config, self.handoff, self.root, record, lambda: None)
        self.assertEqual(record["phase"], "merged")
        self.assertEqual(record["pr_number"], 6)
        merge_calls = [call.args[2] for call in execute.call_args_list
                       if call.args[2][:3] == ["gh", "pr", "merge"]]
        self.assertEqual(len(merge_calls), 1)
        self.assertEqual(merge_calls[0][3], "6")

    def test_merge_rejects_historical_pr_when_recorded_number_is_stale(self):
        from apatch_lib import github

        old_pr = dict(self.details, number=5, state="MERGED", headRefOid="b" * 40)
        current_pr = dict(self.details, number=6, state="OPEN")
        with patch.object(github, "require_clean"), \
                patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[old_pr, current_pr]), \
                patch.object(github, "pr_details") as details, \
                patch.object(github, "gh_run") as execute:
            with self.assertRaisesRegex(Abort, "Recorded open PR identity"):
                github.merge_pr(self.config, self.handoff, self.root, self.record, lambda: None)
        details.assert_not_called()
        execute.assert_not_called()

    def test_pr_creation_verification_rejects_competing_open_pr(self):
        from apatch_lib import github

        other_open = dict(self.details, number=5, headRefOid="b" * 40)
        current_pr = dict(self.details, number=6)
        record = {"phase": "pushed", "pushed_sha": self.sha}
        with patch.object(github, "require_clean"), \
                patch.object(github, "head", return_value=self.sha), \
                patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "remote_head", return_value=self.sha), \
                patch.object(github, "pr_list", side_effect=[[], [other_open, current_pr]]), \
                patch.object(github, "gh_run") as execute, \
                patch.object(github, "confirm", return_value=True):
            with self.assertRaisesRegex(RemoteOutcomeUnknown, "no unique matching open PR"):
                github.create_pr(self.config, self.handoff, self.root, record, lambda: None)
        execute.assert_called_once()
        self.assertEqual(record["phase"], "pushed")

    def test_historical_merged_pr_with_same_head_does_not_trigger_duplicate_creation(self):
        from apatch_lib import github

        old_pr = dict(self.details, number=5, state="MERGED")
        record = {"phase": "pushed", "pushed_sha": self.sha}
        with patch.object(github, "require_clean"), patch.object(github, "head", return_value=self.sha), \
                patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "remote_head", return_value=self.sha), \
                patch.object(github, "pr_list", return_value=[old_pr]), \
                patch.object(github, "gh_run") as execute:
            with self.assertRaisesRegex(Abort, "already has a closed or merged PR"):
                github.create_pr(self.config, self.handoff, self.root, record, lambda: None)
        execute.assert_not_called()
        self.assertEqual(record["phase"], "pushed")

    def test_merged_pr_sync_rejects_unrelated_pushed_revision(self):
        from apatch_lib import github

        old_pr = dict(self.details, state="MERGED", headRefOid="b" * 40,
                      mergedAt="2026-10-24T06:23:48Z")
        with patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "pr_details", return_value=old_pr), \
                patch.object(github, "sync_local_base") as sync, \
                patch.object(github, "require_clean"):
            with self.assertRaisesRegex(Abort, "does not contain the current patch revision"):
                github.sync_base(self.config, self.handoff, self.root, self.record, lambda: None)
        sync.assert_not_called()
        self.assertEqual(self.record["phase"], "pr_created")

    def test_merged_pr_status_rejects_unrelated_commit(self):
        from apatch_lib import github

        old_pr = dict(self.details, state="MERGED", headRefOid="b" * 40)
        with patch.object(github, "remote_repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[old_pr]):
            with self.assertRaisesRegex(Abort, "for the current patch revision"):
                github.confirmed_merged_pr(self.config, self.handoff, self.root, self.record)

    def test_sync_selects_matching_revision_among_historical_merged_prs(self):
        from apatch_lib import github

        old_pr = dict(self.details, number=5, state="MERGED", headRefOid="b" * 40)
        new_pr = dict(self.details, number=6, state="MERGED",
                      mergedAt="2026-10-24T06:23:48Z")
        record = dict(self.record, pr_number=6)
        with patch.object(github, "remote_repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[old_pr, new_pr]) as lookup:
            selected = github.confirmed_merged_pr(self.config, self.handoff, self.root, record)
        self.assertEqual(selected["number"], 6)
        lookup.assert_called_once()

    def test_synced_status_does_not_accept_merged_pr_without_merge_timestamp(self):
        from apatch_lib import github

        missing_timestamp = dict(self.details, state="MERGED", mergedAt=None)
        with patch.object(github, "remote_repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[missing_timestamp]):
            with self.assertRaisesRegex(Abort, "not confirmed"):
                github.confirmed_merged_pr(self.config, self.handoff, self.root, self.record)

    def test_post_merge_confirmation_rechecks_pr_head(self):
        from apatch_lib import github

        after = dict(self.details, state="MERGED", headRefOid="b" * 40,
                     mergedAt="2026-10-24T06:23:48Z")
        with patch.object(github, "require_clean"), \
                patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[dict(self.details)]), \
                patch.object(github, "pr_details", side_effect=[dict(self.details), after]), \
                patch.object(github, "remote_head", return_value=self.sha), \
                patch.object(github, "gh_run"), \
                patch.object(github, "confirm", return_value=True):
            with self.assertRaisesRegex(Abort, "does not contain the current patch revision"):
                github.merge_pr(self.config, self.handoff, self.root, self.record, lambda: None)
        self.assertEqual(self.record["phase"], "pr_created")

    def test_all_gh_commands_receive_configured_timeout(self):
        from apatch_lib import github
        from dataclasses import replace
        config = replace(self.config, github_timeout_seconds=19)
        with patch.object(github, "run") as fake_run, patch.object(github, "output", return_value="ok") as fake_output:
            github.gh_run(config, self.root, ["gh", "auth", "status"])
            github.gh_output(config, self.root, ["gh", "pr", "list"])
        self.assertEqual(fake_run.call_args.kwargs["timeout"], 19)
        self.assertEqual(fake_output.call_args.kwargs["timeout"], 19)

    def test_transient_github_graphql_read_timeout_retries_once(self):
        from apatch_lib import github

        with patch.object(github, "output", side_effect=[
                Abort('Post "https://api.github.com/graphql": dial tcp: i/o timeout'),
                "example/repo",
        ]) as fetch, patch.object(github.time, "sleep") as pause:
            result = github.gh_output(self.config, self.root,
                                      ["gh", "repo", "view", "--json", "nameWithOwner"])
        self.assertEqual(result, "example/repo")
        self.assertEqual(fetch.call_count, 2)
        pause.assert_called_once_with(0.5)

    def test_github_read_failure_does_not_retry_non_transient_error(self):
        from apatch_lib import github

        with patch.object(github, "output", side_effect=Abort("authentication required")) as fetch, \
                patch.object(github.time, "sleep") as pause:
            with self.assertRaisesRegex(Abort, "authentication required"):
                github.gh_output(self.config, self.root, ["gh", "pr", "list"])
        fetch.assert_called_once()
        pause.assert_not_called()

    def test_github_read_retries_are_bounded_on_repeated_timeout(self):
        from apatch_lib import github

        with patch.object(github, "output", side_effect=Abort("command timed out after 45s")) as fetch, \
                patch.object(github.time, "sleep") as pause:
            with self.assertRaisesRegex(Abort, "timed out"):
                github.gh_output(self.config, self.root, ["gh", "pr", "view"])
        self.assertEqual(fetch.call_count, 2)
        pause.assert_called_once()

    def test_github_mutating_commands_are_not_retried(self):
        from apatch_lib import github

        for action in ("create", "merge"):
            with self.subTest(action=action), \
                    patch.object(github, "run", side_effect=Abort("i/o timeout")) as execute, \
                    patch.object(github.time, "sleep") as pause:
                with self.assertRaisesRegex(Abort, "i/o timeout"):
                    github.gh_run(self.config, self.root, ["gh", "pr", action])
                execute.assert_called_once()
                pause.assert_not_called()

    def test_verified_repository_reuses_identity_but_rechecks_git_remote(self):
        from apatch_lib import github

        with patch.object(github, "repository") as api, \
                patch.object(github, "remote_repository", return_value="example/repo") as git:
            self.assertEqual(github.verified_repository(self.config, self.root,
                                                        "example/repo"), "example/repo")
        api.assert_not_called()
        git.assert_called_once()

        with patch.object(github, "repository") as api, \
                patch.object(github, "remote_repository", return_value="other/repo"):
            with self.assertRaisesRegex(Abort, "changed after verifying"):
                github.verified_repository(self.config, self.root, "example/repo")
        api.assert_not_called()

    def test_merge_and_sync_reuse_validated_github_identity(self):
        from apatch_lib import github

        merged = dict(self.details, state="MERGED", mergedAt="2026-10-24T06:23:48Z")
        with patch.object(github, "require_clean"), \
                patch.object(github, "repository") as api, \
                patch.object(github, "remote_repository", return_value="example/repo") as git, \
                patch.object(github, "pr_list", return_value=[dict(self.details)]), \
                patch.object(github, "pr_details",
                             side_effect=[dict(self.details), merged, merged]), \
                patch.object(github, "remote_head", return_value=self.sha), \
                patch.object(github, "gh_run"), \
                patch.object(github, "confirm", return_value=True), \
                patch.object(github, "sync_local_base", return_value=self.sha):
            repo = github.merge_pr(self.config, self.handoff, self.root, self.record,
                                   lambda: None, verified_repo="example/repo")
            github.sync_base(self.config, self.handoff, self.root, self.record,
                             lambda: None, verified_repo=repo)
        api.assert_not_called()
        self.assertEqual(git.call_count, 2)
        self.assertEqual(self.record["phase"], "synced")

    def test_timeout_raises_abort_without_waiting_indefinitely(self):
        from apatch_lib.gitutil import run
        with self.assertRaisesRegex(Abort, "timed out after 0.1s"):
            run([sys.executable, "-c", "import time; time.sleep(20)"],
                self.root, timeout=0.1)

    def test_network_timeout_kills_descendants_holding_output_pipes(self):
        from apatch_lib.gitutil import run
        started = time.monotonic()
        child = "import subprocess, sys, time; " \
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)']); " \
                "time.sleep(20)"
        with self.assertRaisesRegex(Abort, "timed out after 0.2s"):
            run([sys.executable, "-c", child], self.root, timeout=0.2)
        self.assertLess(time.monotonic() - started, 3)

    def test_network_timeout_when_parent_exits_but_child_holds_pipe(self):
        from apatch_lib.gitutil import run

        script = "import subprocess, sys; " \
                 "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])"
        started = time.monotonic()
        with self.assertRaisesRegex(Abort, "timed out after 0.2s"):
            run([sys.executable, "-c", script], self.root, timeout=0.2)
        self.assertLess(time.monotonic() - started, 3)

    def test_remote_git_head_uses_configured_timeout(self):
        from apatch_lib import gitutil
        from unittest.mock import Mock

        with patch.object(gitutil, "run", return_value=Mock(stdout="")) as read:
            self.assertIsNone(gitutil.remote_head(self.root, self.config, "feature/a"))
        self.assertEqual(read.call_args.kwargs["timeout"], 30)

    def test_global_github_timeout_is_validated(self):
        original = (TOOL / "apatch.conf").read_text()
        for value in ("0", "4", "301", "one-minute"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)
                (path / "apatch.conf").write_text(original.replace("github_timeout_seconds = 30",
                                                                   f"github_timeout_seconds = {value}"))
                with self.assertRaisesRegex(Abort, "github_timeout_seconds"):
                    load_config(path)

    def test_sync_status_uses_one_pr_listing_and_validates_identity(self):
        from unittest.mock import patch
        from apatch_lib import github

        merged = dict(self.details, state="MERGED", mergedAt="2026-10-24T06:23:48Z")
        with patch.object(github, "remote_repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[merged]) as list_prs, \
             patch.object(github, "pr_details") as details:
            result = github.confirmed_merged_pr(self.config, self.handoff, self.root, self.record)
        self.assertEqual(result["number"], 4)
        list_prs.assert_called_once()
        details.assert_not_called()

        with patch.object(github, "remote_repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[dict(merged, number=5)]):
            with self.assertRaisesRegex(Abort, "recorded PR number"):
                github.confirmed_merged_pr(self.config, self.handoff, self.root, self.record)

    def test_unmerged_pr_does_not_confirm_synchronization(self):
        from unittest.mock import patch
        from apatch_lib import github

        with patch.object(github, "remote_repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[self.details]):
            with self.assertRaisesRegex(Abort, "not confirmed"):
                github.confirmed_merged_pr(self.config, self.handoff, self.root, self.record)

    def test_strict_sync_still_requires_live_merge_confirmation(self):
        from unittest.mock import patch
        from apatch_lib import github

        with patch.object(github, "require_clean"), \
             patch.object(github, "repository", side_effect=Abort("GitHub API timeout")), \
             patch.object(github, "sync_local_base") as sync_git:
            with self.assertRaisesRegex(Abort, "timeout"):
                github.sync_base(self.config, self.handoff, self.root, self.record, lambda: None)
        sync_git.assert_not_called()
