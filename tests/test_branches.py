"""Regression tests for the branches subsystem."""

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


class BranchesTests(LocalGitFixture):
    def test_unmerged_local_feature_branch_blocks_new_creation_in_all_modes(self):
        command("git", "switch", "-c", "feature/unfinished-local", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Unfinished local work", cwd=self.root)
        command("git", "switch", "main", cwd=self.root)
        for mode in ("strict", "loose", "force"):
            with self.subTest(mode=mode):
                result = self.invoke_cli(f"--{mode}", "op=BRN", "skipApproves=true")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("Unfinished local feature branch feature/unfinished-local", result.stderr)
                self.assertIn("Finish it before creating", result.stderr)
                self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
                self.assertFalse(command("git", "branch", "--list", self.payload["feature_branch"],
                                         cwd=self.root).stdout.strip())

    def test_unmerged_remote_feature_branch_blocks_new_creation_in_all_modes(self):
        command("git", "switch", "-c", "feature/unfinished-remote", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Unmerged remote work", cwd=self.root)
        command("git", "push", "origin", "feature/unfinished-remote", cwd=self.root)
        command("git", "switch", "main", cwd=self.root)
        command("git", "branch", "-D", "feature/unfinished-remote", cwd=self.root)
        for mode in ("strict", "loose", "force"):
            with self.subTest(mode=mode):
                result = self.invoke_cli(f"--{mode}", "op=BRN", "skipApproves=true")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("сначала смерджи fb: feature/unfinished-remote", result.stderr)
                self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
                self.assertFalse(command("git", "branch", "--list", self.payload["feature_branch"],
                                         cwd=self.root).stdout.strip())

    def test_merged_local_and_remote_feature_branch_does_not_block_new_creation(self):
        command("git", "switch", "-c", "feature/already-merged", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Already merged work", cwd=self.root)
        command("git", "push", "origin", "feature/already-merged", cwd=self.root)
        command("git", "switch", "main", cwd=self.root)
        command("git", "merge", "--ff-only", "feature/already-merged", cwd=self.root)
        command("git", "push", "origin", "main", cwd=self.root)
        self.payload["base_commit"] = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.params.write_text(json.dumps(self.payload))
        result = self.invoke_cli("--strict", "op=BRN", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Feature branch preflight passed", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])

    def test_feature_branch_with_uncommitted_changes_blocks_new_creation_in_loose(self):
        command("git", "switch", "-c", "feature/uncommitted", cwd=self.root)
        (self.root / "existing.txt").write_text("local work\n")
        result = self.invoke_cli("--loose", "op=BRN", "skipApproves=true")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("feature/uncommitted has uncommitted changes", result.stderr)
        self.assertFalse(command("git", "branch", "--list", self.payload["feature_branch"],
                                 cwd=self.root).stdout.strip())

    def test_unavailable_branch_preflight_fails_closed(self):
        from apatch_lib.branch_guard import assert_no_unfinished_feature_branches

        config = load_project_config(self.root, load_config(self.bin))
        with patch("apatch_lib.branch_guard._remote_heads", side_effect=Abort("network timeout")):
            with self.assertRaisesRegex(Abort, "new feature branch creation blocked"):
                assert_no_unfinished_feature_branches(self.root, config, self.payload["feature_branch"])

    def test_open_github_feature_pr_blocks_new_branch_even_when_remote_branch_is_gone(self):
        from apatch_lib.branch_guard import assert_no_unfinished_feature_branches

        config = load_project_config(self.root, load_config(self.bin))
        pull_requests = [{"number": 17, "state": "OPEN", "headRefName": "feature/old-pr",
                          "baseRefName": "main", "headRefOid": "a" * 40,
                          "url": "https://github.com/example/repo/pull/17"}]
        with patch("apatch_lib.branch_guard._is_github_remote", return_value=True), \
                patch("apatch_lib.branch_guard._github_prs", return_value=pull_requests):
            with self.assertRaisesRegex(Abort, "сначала смерджи fb: feature/old-pr"):
                assert_no_unfinished_feature_branches(self.root, config, self.payload["feature_branch"])

    def test_matching_merged_github_pr_proves_squash_merged_branch(self):
        from apatch_lib.branch_guard import assert_no_unfinished_feature_branches

        config = load_project_config(self.root, load_config(self.bin))
        tip = "a" * 40
        merged_pr = [{"number": 3, "state": "MERGED", "headRefName": "feature/squash-merged",
                      "baseRefName": "main", "headRefOid": tip}]
        with patch("apatch_lib.branch_guard._is_github_remote", return_value=True), \
                patch("apatch_lib.branch_guard._remote_heads",
                      return_value=(self.head, {"feature/squash-merged": tip})), \
                patch("apatch_lib.branch_guard._github_prs", return_value=merged_pr):
            assert_no_unfinished_feature_branches(self.root, config, self.payload["feature_branch"])

    def test_mismatched_merged_pr_does_not_authorize_new_branch(self):
        from apatch_lib.branch_guard import assert_no_unfinished_feature_branches

        config = load_project_config(self.root, load_config(self.bin))
        merged_pr = [{"number": 3, "state": "MERGED", "headRefName": "feature/changed-after-merge",
                      "baseRefName": "main", "headRefOid": "b" * 40}]
        with patch("apatch_lib.branch_guard._is_github_remote", return_value=True), \
                patch("apatch_lib.branch_guard._remote_heads",
                      return_value=(self.head, {"feature/changed-after-merge": "a" * 40})), \
                patch("apatch_lib.branch_guard._github_prs", return_value=merged_pr):
            with self.assertRaisesRegex(Abort, "сначала смерджи fb: feature/changed-after-merge"):
                assert_no_unfinished_feature_branches(self.root, config, self.payload["feature_branch"])

    def test_remote_merge_not_pushed_to_main_still_blocks_new_branch(self):
        from apatch_lib.branch_guard import assert_no_unfinished_feature_branches

        command("git", "switch", "-c", "feature/local-merge-only", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Feature not merged remotely", cwd=self.root)
        tip = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        command("git", "push", "origin", "feature/local-merge-only", cwd=self.root)
        command("git", "switch", "main", cwd=self.root)
        command("git", "merge", "--ff-only", "feature/local-merge-only", cwd=self.root)
        config = load_project_config(self.root, load_config(self.bin))
        self.assertNotEqual(self.head, tip)
        with self.assertRaisesRegex(Abort, "сначала смерджи fb: feature/local-merge-only"):
            assert_no_unfinished_feature_branches(self.root, config, self.payload["feature_branch"])

    def test_combined_create_and_apply_rejects_prior_feature_without_unpacking(self):
        command("git", "switch", "-c", "feature/unfinished-before-bap", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Pending prior work", cwd=self.root)
        command("git", "switch", "main", cwd=self.root)
        for mode in ("strict", "loose", "force"):
            with self.subTest(mode=mode):
                result = self.invoke_cli(f"--{mode}", "op=BAP", "skipApproves=true")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("Unfinished local feature branch", result.stderr)
                self.assertFalse((self.root / "new.txt").exists())
                self.assertEqual((self.root / "existing.txt").read_text(), "old\n")
                self.assertFalse(command("git", "branch", "--list", self.payload["feature_branch"],
                                         cwd=self.root).stdout.strip())
                self.assertFalse(self.history_path.exists())

    def test_existing_feature_branch_can_be_reused_despite_other_unfinished_branch(self):
        command("git", "switch", "-c", "feature/unfinished-other", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Other unfinished branch", cwd=self.root)
        command("git", "switch", "main", cwd=self.root)
        command("git", "branch", self.payload["feature_branch"], cwd=self.root)
        result = self.invoke_cli("--force", "op=BRN", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])

    def test_github_preflight_failure_is_not_bypassed(self):
        from apatch_lib.branch_guard import assert_no_unfinished_feature_branches

        config = load_project_config(self.root, load_config(self.bin))
        with patch("apatch_lib.branch_guard._is_github_remote", return_value=True), \
                patch("apatch_lib.branch_guard._github_prs", side_effect=Abort("GitHub timeout")):
            with self.assertRaisesRegex(Abort, "GitHub timeout"):
                assert_no_unfinished_feature_branches(self.root, config, self.payload["feature_branch"])

    def test_remote_base_head_mismatch_prevents_branch_creation(self):
        command("git", "commit", "--allow-empty", "-m", "local only", cwd=self.root)
        self.payload["base_commit"] = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.params.write_text(json.dumps(self.payload))
        result = self.invoke("1\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Local base HEAD differs", result.stderr)
