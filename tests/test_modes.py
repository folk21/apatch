"""Regression tests for the modes subsystem."""

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


class ModesTests(LocalGitFixture):
    def test_loose_sync_switches_main_even_if_github_is_unavailable(self):
        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        result = self.invoke_cli("op=SYN", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        self.assertIn("Local main synchronized with origin/main", result.stdout)
        self.assertIn("PR merge verification is pending", result.stdout)
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["local_base_head"], self.head)
        self.assertNotEqual(record.get("phase"), "synced")

    def test_force_sync_switches_main_before_github_timeout(self):
        from unittest.mock import patch
        from apatch_lib import github
        from apatch_lib.workflow import Workflow

        config = load_project_config(self.root, load_config(self.bin))
        handoff = load_handoff(self.params)
        workflow = Workflow(self.root, config, handoff, {"schema_version": 1, "workflows": {}},
                            force=True)
        workflow.record.update(phase="pr_created", applied_branch=handoff.branch,
                               pr_number=1, pushed_sha=self.head)
        command("git", "switch", "-c", handoff.branch, cwd=self.root)
        with patch.object(github, "confirmed_merged_pr", side_effect=Abort("GitHub API timeout")) as lookup:
            workflow.force_actions.sync()
        lookup.assert_called_once()
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        self.assertEqual(workflow.phase, "pr_created")
        saved = json.loads(self.state_path.read_text())["workflows"][workflow.key]
        self.assertEqual(saved["local_base_head"], self.head)
        self.assertEqual(saved["phase"], "pr_created")

    def test_force_sync_reconciles_verified_merge_after_local_update(self):
        from unittest.mock import patch
        from apatch_lib import github
        from apatch_lib.workflow import Workflow

        config = load_project_config(self.root, load_config(self.bin))
        handoff = load_handoff(self.params)
        workflow = Workflow(self.root, config, handoff, {"schema_version": 1, "workflows": {}},
                            force=True)
        workflow.record.update(phase="pr_created", applied_branch=handoff.branch, pr_number=1)
        command("git", "switch", "-c", handoff.branch, cwd=self.root)
        with patch.object(github, "confirmed_merged_pr", return_value={"number": 1}) as lookup:
            workflow.force_actions.sync()
        lookup.assert_called_once()
        self.assertEqual(workflow.phase, "synced")
        self.assertEqual(workflow.record["local_base_head"], self.head)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")

    def test_force_merge_cannot_adopt_historical_merged_pr_for_new_commit(self):
        from apatch_lib import github
        from apatch_lib.workflow import Workflow

        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Current unmerged patch", cwd=self.root)
        current_sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        config = load_project_config(self.root, load_config(self.bin))
        handoff = load_handoff(self.params)
        workflow = Workflow(self.root, config, handoff, {"schema_version": 1, "workflows": {}}, force=True)
        workflow.record.update(phase="pushed", applied_branch=handoff.branch,
                               commit_sha=current_sha, pushed_sha=current_sha)
        old_pr = {"number": 5, "state": "MERGED", "headRefName": handoff.branch,
                  "baseRefName": "main", "headRefOid": self.head}
        with patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[old_pr]), \
                patch.object(github, "pr_details") as details, \
                patch.object(github, "sync_base") as sync:
            with self.assertRaisesRegex(Abort, "older revision"):
                workflow.force_actions.merge()
        details.assert_not_called()
        sync.assert_not_called()
        self.assertEqual(workflow.phase, "pushed")
        self.assertNotIn("pr_number", workflow.record)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         handoff.branch)

    def test_force_merge_accepts_matching_new_pr_with_historical_merged_pr_present(self):
        from apatch_lib import github
        from apatch_lib.workflow import Workflow

        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Current patch", cwd=self.root)
        current_sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        config = load_project_config(self.root, load_config(self.bin))
        handoff = load_handoff(self.params)
        workflow = Workflow(self.root, config, handoff, {"schema_version": 1, "workflows": {}}, force=True)
        workflow.record.update(phase="pr_created", applied_branch=handoff.branch,
                               commit_sha=current_sha, pushed_sha=current_sha, pr_number=6)
        old_pr = {"number": 5, "state": "MERGED", "headRefName": handoff.branch,
                  "baseRefName": "main", "headRefOid": self.head}
        new_pr = {"number": 6, "state": "OPEN", "headRefName": handoff.branch,
                  "baseRefName": "main", "headRefOid": current_sha}
        with patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[old_pr, new_pr]), \
                patch("apatch_lib.force.remote_head", return_value=current_sha), \
                patch.object(github, "merge_pr") as merge:
            workflow.force_actions.merge()
        merge.assert_called_once()
        self.assertEqual(workflow.record["pr_number"], 6)
        self.assertEqual(workflow.record["pushed_sha"], current_sha)

    def test_force_merge_reuses_one_repository_identity_for_merge_and_sync(self):
        from apatch_lib import github
        from apatch_lib.workflow import Workflow

        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Current patch", cwd=self.root)
        current_sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        config = load_project_config(self.root, load_config(self.bin))
        handoff = load_handoff(self.params)
        workflow = Workflow(self.root, config, handoff, {"schema_version": 1, "workflows": {}},
                            force=True)
        workflow.record.update(phase="pr_created", applied_branch=handoff.branch,
                               commit_sha=current_sha, pushed_sha=current_sha, pr_number=6)
        pr = {"number": 6, "state": "OPEN", "headRefName": handoff.branch,
              "baseRefName": "main", "headRefOid": current_sha}

        def adopt_merged(_config, _handoff, _root, record, _persist, **_kwargs):
            record["phase"] = "merged"

        with patch.object(github, "repository", return_value="example/repo") as resolved, \
                patch.object(github, "pr_list", return_value=[pr]), \
                patch("apatch_lib.force.remote_head", return_value=current_sha), \
                patch.object(github, "merge_pr", side_effect=adopt_merged) as merge, \
                patch.object(github, "sync_base") as sync:
            workflow.force_actions.merge()
        resolved.assert_called_once()
        self.assertEqual(merge.call_args.kwargs, {"verified_repo": "example/repo"})
        self.assertEqual(sync.call_args.kwargs, {"verified_repo": "example/repo"})

    def test_synced_checkpoint_requires_revision_reverification(self):
        from apatch_lib import github
        from apatch_lib.workflow import Workflow

        config = load_project_config(self.root, load_config(self.bin))
        handoff = load_handoff(self.params)
        workflow = Workflow(self.root, config, handoff, {"schema_version": 1, "workflows": {}}, force=True)
        workflow.record.update(phase="synced", applied_branch=handoff.branch,
                               pushed_sha="a" * 40, pr_number=5)
        old_pr = {"number": 5, "state": "MERGED", "headRefName": handoff.branch,
                  "baseRefName": "main", "headRefOid": self.head}
        console = StringIO()
        with patch.object(github, "remote_repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[old_pr]), \
                redirect_stdout(console):
            workflow.force_actions.sync()
        self.assertEqual(workflow.phase, "synced")
        self.assertIn("could not be verified", console.getvalue())
        self.assertNotIn("reverified for the current patch", console.getvalue())

    def test_synced_checkpoint_returns_positive_evidence_for_matching_merged_pr(self):
        from apatch_lib import github
        from apatch_lib.workflow import Workflow

        config = load_project_config(self.root, load_config(self.bin))
        handoff = load_handoff(self.params)
        workflow = Workflow(self.root, config, handoff, {"schema_version": 1, "workflows": {}}, force=True)
        workflow.record.update(phase="synced", applied_branch=handoff.branch,
                               pushed_sha=self.head, pr_number=5)
        matching_pr = {"number": 5, "state": "MERGED", "mergedAt": "2026-10-25T00:00:00Z",
                       "headRefName": handoff.branch, "baseRefName": "main", "headRefOid": self.head}
        console = StringIO()
        with patch.object(github, "remote_repository", return_value="example/repo"), \
                patch.object(github, "pr_list", return_value=[matching_pr]), \
                redirect_stdout(console):
            evidence = workflow.force_actions.sync()
        self.assertIs(evidence, True)
        self.assertEqual(workflow.phase, "synced")
        self.assertIn("merge was reverified for the current patch revision", console.getvalue())

    def test_sync_git_failure_is_not_reported_as_success(self):
        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        command("git", "remote", "set-url", "origin", str(self.base / "missing-remote.git"), cwd=self.root)
        result = self.invoke_cli("op=SYN", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        self.assertIn("remote synchronization is incomplete", result.stdout)
        self.assertNotIn("PR merge verification is pending", result.stdout)

    def test_sync_creates_missing_local_main_from_remote(self):
        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        command("git", "branch", "-D", "main", cwd=self.root)
        result = self.invoke_cli("op=SYN", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)

    def test_loose_applies_on_another_branch_and_commits_without_pushing(self):
        applied = self.invoke_loose("3\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("not the planned branch", applied.stdout)
        self.assert_history(real_branch="main")
        checked = self.invoke_loose("4\n")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        committed = self.invoke_loose("5\nYES\nYES\n")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertIn("Push remains a separate action", committed.stdout)
        local_sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        remote_before = command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                                cwd=self.root).stdout.split()[0]
        self.assertNotEqual(local_sha, remote_before)
        self.assert_history(real_branch="main")
        pushed = self.invoke_loose("6\nYES\n")
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        remote_after = command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                               cwd=self.root).stdout.split()[0]
        self.assertEqual(local_sha, remote_after)

    def test_loose_accepts_manual_edits_after_verification(self):
        self.assertEqual(self.invoke_loose("3\nYES\n").returncode, 0)
        self.assertEqual(self.invoke_loose("4\n").returncode, 0)
        (self.root / "manual.txt").write_text("added by developer\n")
        (self.root / "existing.txt").write_text("edited after verification\n")
        committed = self.invoke_loose("5\nYES\nYES\n")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertIn("have not passed canonical checks", committed.stdout)
        changed = command("git", "show", "--pretty=", "--name-only", "HEAD",
                          cwd=self.root).stdout.splitlines()
        self.assertEqual(set(changed), {"existing.txt", "new.txt", "manual.txt"})

    def test_loose_preserves_preexisting_unrelated_edits_when_applying_patch(self):
        (self.root / "manual.txt").write_text("untouched manual work\n")
        applied = self.invoke_loose("3\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("pre-existing changed path", applied.stdout)
        self.assertEqual((self.root / "manual.txt").read_text(), "untouched manual work\n")
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")
        committed = self.invoke_loose("5\nYES\nYES\n")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        changed = command("git", "show", "--pretty=", "--name-only", "HEAD",
                          cwd=self.root).stdout.splitlines()
        self.assertIn("manual.txt", changed)

    def test_loose_allows_committing_on_different_branch_after_manual_switch(self):
        self.assertEqual(self.invoke_loose("3\nYES\n").returncode, 0)
        command("git", "switch", "-c", "feature/manual-destination", cwd=self.root)
        result = self.invoke_loose("5\nYES\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not the planned branch", result.stdout)
        self.assert_history(real_branch="feature/manual-destination")
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["phase"], "committed")
        self.assertEqual(record["applied_branch"], "feature/manual-destination")

    def test_loose_manual_commit_does_not_invent_applied_patch_history(self):
        (self.root / "manual.txt").write_text("manual\n")
        command("git", "add", "manual.txt", cwd=self.root)
        committed = self.invoke_loose("5\nYES\nYES\n")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertFalse(self.history_path.exists())
        self.assertEqual(command("git", "log", "-1", "--format=%s",
                                 cwd=self.root).stdout.strip(), "test: apply guarded patch")

    def test_loose_allows_multiple_patches_one_commit_with_overlap_backup(self):
        self.assertEqual(self.invoke_loose("3\nYES\n").returncode, 0)
        second_zip = self.base / "downloads" / "example_service-PATCH-batched.zip"
        with zipfile.ZipFile(second_zip, "w") as archive:
            archive.writestr("example_service/existing.txt", "updated twice\n")
            archive.writestr("example_service/another.txt", "extra\n")
        self.payload["patch_file"] = second_zip.name
        self.payload["patch_sha256"] = hashlib.sha256(second_zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))
        applied = self.invoke_loose("3\nYES\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("pre-existing changed", applied.stdout)
        self.assertIn("Backed up 1 overlapping file", applied.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated twice\n")
        backups = list((self.root / ".apatch" / "backups").glob("overlap-*/existing.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "updated\n")
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 2)
        self.assertEqual(self.invoke_loose("4\n").returncode, 0)
        committed = self.invoke_loose("5\nYES\nYES\n")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertIn("Associated pending patches", committed.stdout)
        changed = command("git", "show", "--pretty=", "--name-only", "HEAD",
                          cwd=self.root).stdout.splitlines()
        self.assertEqual(set(changed), {"existing.txt", "new.txt", "another.txt"})
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        state = json.loads(self.state_path.read_text())
        self.assertEqual(len(state["workflows"]), 2)
        self.assertTrue(all(item["phase"] == "committed" for item in state["workflows"].values()))
        self.assertEqual(self.invoke_loose("6\nYES\n").returncode, 0)
        updated = json.loads(self.state_path.read_text())
        self.assertTrue(all(item["phase"] == "pushed" for item in updated["workflows"].values()))

    def test_loose_can_push_multiple_local_commits_together(self):
        self.assertEqual(self.invoke_loose("3\nYES\n").returncode, 0)
        self.assertEqual(self.invoke_loose("5\nYES\nYES\n").returncode, 0)
        first_sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        second_zip = self.base / "downloads" / "example_service-PATCH-followup.zip"
        with zipfile.ZipFile(second_zip, "w") as archive:
            archive.writestr("example_service/followup.txt", "followup\n")
        self.payload["patch_file"] = second_zip.name
        self.payload["patch_sha256"] = hashlib.sha256(second_zip.read_bytes()).hexdigest()
        self.payload["base_commit"] = first_sha
        self.params.write_text(json.dumps(self.payload))
        self.assertEqual(self.invoke_loose("3\nYES\n").returncode, 0)
        self.assertEqual(self.invoke_loose("5\nYES\nYES\n").returncode, 0)
        second_sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.assertNotEqual(first_sha, second_sha)
        self.assertEqual(self.invoke_loose("6\nYES\n").returncode, 0)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(len(state["workflows"]), 2)
        self.assertTrue(all(item["phase"] == "pushed" for item in state["workflows"].values()))
        self.assertEqual(command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                                 cwd=self.root).stdout.split()[0], second_sha)

    def test_loose_rejects_overwrite_when_developer_declines(self):
        self.assertEqual(self.invoke_loose("3\nYES\n").returncode, 0)
        second_zip = self.base / "downloads" / "example_service-PATCH-overlap.zip"
        with zipfile.ZipFile(second_zip, "w") as archive:
            archive.writestr("example_service/existing.txt", "should not overwrite\n")
        self.payload["patch_file"] = second_zip.name
        self.payload["patch_sha256"] = hashlib.sha256(second_zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))
        rejected = self.invoke_loose("3\nno\n")
        self.assertEqual(rejected.returncode, 0, rejected.stderr)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 1)

    def test_loose_whitespace_warnings_do_not_block_checks_or_commit(self):
        self.assertEqual(self.invoke_loose("3\nYES\n").returncode, 0)
        (self.root / "existing.txt").write_text("updated\n\n")
        checked = self.invoke_loose("4\n")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("Git whitespace check reported problems", checked.stdout)
        committed = self.invoke_loose("5\nYES\nYES\n")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertIn("Staged changes contain Git whitespace warnings", committed.stdout)

    def test_loose_never_pushes_diverged_remote_history(self):
        self.assertEqual(self.invoke_loose("3\nYES\n").returncode, 0)
        self.assertEqual(self.invoke_loose("5\nYES\nYES\n").returncode, 0)
        local_sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        other = self.base / "another_checkout"
        command("git", "clone", "-b", "main", str(self.remote), str(other), cwd=self.base)
        command("git", "config", "user.email", "other@example.test", cwd=other)
        command("git", "config", "user.name", "Other Developer", cwd=other)
        command("git", "commit", "--allow-empty", "-m", "Divergent remote change", cwd=other)
        command("git", "push", "origin", "main", cwd=other)
        remote_sha = command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                             cwd=self.root).stdout.split()[0]
        self.assertNotEqual(local_sha, remote_sha)
        rejected = self.invoke_loose("6\n")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("never force-pushes", rejected.stderr)
        self.assertEqual(command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                                 cwd=self.root).stdout.split()[0], remote_sha)

    def test_shell_launcher_accepts_force_as_first_or_second_argument(self):
        self.prepare_test_launcher()
        for args in (("force", str(self.params)), (str(self.params), "force"),
                     ("--force", str(self.params))):
            with self.subTest(args=args):
                result = subprocess.run(["sh", str(self.bin / "apatch.sh"), *args],
                                        cwd=self.root, input="0\n", capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Mode: FORCE", result.stdout)

    def test_force_adopts_manually_created_feature_branch(self):
        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        result = self.invoke_force("1\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertEqual(record["phase"], "branch_created")
        self.assertEqual(record["applied_branch"], self.payload["feature_branch"])
        self.assertEqual(record["branch_base"], self.head)
        self.assertEqual(record["force_events"][-1]["action"], "branch prepared")

    def test_force_switches_to_preexisting_local_feature_branch(self):
        command("git", "branch", self.payload["feature_branch"], cwd=self.root)
        result = self.invoke_force("1\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])
        self.assertEqual(len(command("git", "branch", "--list", self.payload["feature_branch"],
                                     cwd=self.root).stdout.splitlines()), 1)

    def test_force_tracks_branch_preexisting_only_on_remote(self):
        command("git", "push", "origin", f"HEAD:refs/heads/{self.payload['feature_branch']}", cwd=self.root)
        self.assertFalse(command("git", "branch", "--list", self.payload["feature_branch"],
                                 cwd=self.root).stdout.strip())
        result = self.invoke_force("1\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)

    def test_force_adopts_manually_extracted_patch_without_overwriting(self):
        (self.root / "existing.txt").write_text("updated\n")
        (self.root / "new.txt").write_text("new\n")
        result = self.invoke_force("3\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["phase"], "patch_applied")
        self.assertEqual(set(record["changed_paths"]), {"existing.txt", "new.txt"})
        self.assert_history(real_branch="main")
        result = self.invoke_force("4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Canonical checks passed", result.stdout)
        self.assertEqual(next(iter(json.loads(self.state_path.read_text())["workflows"].values()))["phase"],
                         "verified")

    def test_force_repeated_adoption_is_successful_with_unchanged_path_set(self):
        (self.root / "existing.txt").write_text("manual modification\n")
        (self.root / "new.txt").write_text("new\n")
        first = self.invoke_force("3\nYES\n")
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        before = command("git", "status", "--porcelain", cwd=self.root).stdout
        repeated = self.invoke_force("3\nYES\n")
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual(before, command("git", "status", "--porcelain", cwd=self.root).stdout)
        self.assertIn("RESULT 3 [APL]: SUCCESS", repeated.stdout)
        self.assertIn("Patch application/adoption completed and was checkpointed", repeated.stdout)

    def test_force_warns_when_manual_worktree_differs_from_zip_contents(self):
        (self.root / "existing.txt").write_text("manual edits\n")
        (self.root / "new.txt").write_text("new\n")
        result = self.invoke_force("3\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("manual override", result.stdout)
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertTrue(record["manually_adopted"])
        self.assertEqual((self.root / "existing.txt").read_text(), "manual edits\n")

    def test_force_can_apply_after_manual_head_changes(self):
        command("git", "commit", "--allow-empty", "-m", "Manual baseline", cwd=self.root)
        result = self.invoke_force("3\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Patch applied in FORCE mode", result.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")

    def test_force_reconciles_manual_commit_and_push(self):
        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        (self.root / "existing.txt").write_text("updated\n")
        (self.root / "new.txt").write_text("new\n")
        command("git", "add", "-A", cwd=self.root)
        command("git", "commit", "-m", "Manual patch commit", cwd=self.root)
        command("git", "push", "-u", "origin", self.payload["feature_branch"], cwd=self.root)
        result = self.invoke_force("6\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already matches", result.stdout)
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertEqual(record["phase"], "pushed")
        self.assertEqual(record["commit_sha"], command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip())
        self.assertEqual(record["pushed_sha"], record["commit_sha"])
        self.assert_history(real_branch=self.payload["feature_branch"])

    def test_force_pushes_manually_committed_changes_without_rewriting_history(self):
        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        (self.root / "existing.txt").write_text("updated\n")
        (self.root / "new.txt").write_text("new\n")
        command("git", "add", "-A", cwd=self.root)
        command("git", "commit", "-m", "Manual patch commit", cwd=self.root)
        result = self.invoke_force("6\nYES\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FORCE push completed", result.stdout)
        current = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.assertEqual(command("git", "ls-remote", "--heads", "origin",
                                 f"refs/heads/{self.payload['feature_branch']}",
                                 cwd=self.root).stdout.split()[0], current)

    def test_force_rejects_non_fast_forward_remote_push(self):
        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        (self.root / "existing.txt").write_text("updated\n")
        (self.root / "new.txt").write_text("new\n")
        command("git", "add", "-A", cwd=self.root)
        command("git", "commit", "-m", "Manual patch commit", cwd=self.root)
        local_commit = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        command("git", "switch", "main", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Conflicting remote commit", cwd=self.root)
        command("git", "push", "origin", f"HEAD:refs/heads/{self.payload['feature_branch']}", cwd=self.root)
        command("git", "switch", self.payload["feature_branch"], cwd=self.root)
        result = self.invoke_force("6\nYES\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("never rewrites remote history", result.stderr)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), local_commit)

    def test_force_commits_and_pushes_on_current_branch_without_verification(self):
        (self.root / "existing.txt").write_text("updated\n")
        (self.root / "new.txt").write_text("new\n")
        result = self.invoke_force("5\nYES\nYES\nYES\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertEqual(record["phase"], "pushed")
        self.assertEqual(record["applied_branch"], "main")
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        self.assertEqual(command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                                 cwd=self.root).stdout.split()[0], record["pushed_sha"])
        self.assert_history(real_branch="main")

    def test_new_patch_cycle_does_not_supersede_when_only_inspected_or_unavailable(self):
        self.assertEqual(self.invoke("3\nYES\n").returncode, 0)
        original = json.loads(self.state_path.read_text())
        second_zip = self.base / "downloads" / "example_service-PATCH-next.zip"
        with zipfile.ZipFile(second_zip, "w") as archive:
            archive.writestr("example_service/another.txt", "next\n")
        self.payload["patch_file"] = second_zip.name
        self.payload["patch_sha256"] = hashlib.sha256(second_zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))
        exited = self.invoke("0\n")
        self.assertEqual(exited.returncode, 0, exited.stderr)
        self.assertEqual(json.loads(self.state_path.read_text()), original)
        inspected = self.invoke("10\n")
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertIn("PATCH STATUS 10 [STS]", inspected.stdout)
        self.assertEqual(json.loads(self.state_path.read_text()), original)
        unavailable = self.invoke_cli("--strict", "op=3")
        self.assertEqual(unavailable.returncode, 2)
        self.assertIn("Action unavailable:", unavailable.stderr)
        after = json.loads(self.state_path.read_text())
        self.assertEqual(after["workflows"], original["workflows"])
        self.assertEqual(after["operation_runs"][:len(original["operation_runs"])],
                         original["operation_runs"])
        self.assertEqual(len(after["operation_runs"]), len(original["operation_runs"]) + 1)
        self.assertEqual(after["operation_runs"][-1]["outcome"], "FAILED")
        self.assertEqual(after["operation_runs"][-1]["operation"]["code"], "APL")

    def test_apply_patch_to_main_and_verify_without_creating_feature_branch(self):
        menu = self.invoke("0\n")
        self.assertEqual(menu.returncode, 0, menu.stderr)
        self.assertIn(" 3. [APL] Apply patch to current branch (main)\n", menu.stdout)
        applied = self.invoke("3\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Apply", applied.stdout)
        self.assertIn("to main?", applied.stdout)
        self.assertIn("Patch applied", applied.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")
        self.assertFalse(command("git", "branch", "--list", self.payload["feature_branch"],
                                 cwd=self.root).stdout.strip())
        state = json.loads(self.state_path.read_text())
        self.assertEqual(next(iter(state["workflows"].values()))["applied_branch"], "main")
        self.assert_history(real_branch="main")
        verified = self.invoke("4\n")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("Canonical checks passed", verified.stdout)
        blocked = self.invoke("5\n")
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn("patch was applied to main", blocked.stderr)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)

    def test_apply_patch_to_another_checked_out_branch(self):
        command("git", "switch", "-c", "release/manual-patch", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "release baseline", cwd=self.root)
        self.payload.pop("base_commit")
        self.params.write_text(json.dumps(self.payload))
        menu = self.invoke("0\n")
        self.assertIn("Apply patch to current branch (release/manual-patch)", menu.stdout)
        applied = self.invoke("3\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("to release/manual-patch?", applied.stdout)
        verified = self.invoke("4\n")
        self.assertEqual(verified.returncode, 0, verified.stderr)

    def test_apply_patch_to_main_after_feature_branch_was_created(self):
        created = self.invoke("1\nYES\n")
        self.assertEqual(created.returncode, 0, created.stderr)
        command("git", "switch", "main", cwd=self.root)
        menu = self.invoke("0\n")
        self.assertIn(" 3. [APL] Apply patch to current branch (main)\n", menu.stdout)
        applied = self.invoke("3\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(self.invoke("4\n").returncode, 0)

    def test_patch_branch_restriction_can_be_enabled_in_config(self):
        conf = self.bin / "apatch.conf"
        conf.write_text(conf.read_text().replace("require_patch_feature_branch = false",
                                                "require_patch_feature_branch = true"))
        menu = self.invoke("0\n")
        self.assertIn(" 3. [APL] Apply patch to current branch (main) * (requires current branch: "
                      + self.payload["feature_branch"] + ")", menu.stdout)
        blocked = self.invoke("3\n")
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn("Action unavailable: requires current branch", blocked.stderr)
        self.assertFalse((self.root / "new.txt").exists())

    def test_patch_menu_disables_detached_head(self):
        command("git", "switch", "--detach", "HEAD", cwd=self.root)
        menu = self.invoke("0\n")
        self.assertIn("Apply patch to current branch (detached HEAD)", menu.stdout)
        self.assertIn("requires a checked-out branch", menu.stdout)
        blocked = self.invoke("3\n")
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn("requires a checked-out branch", blocked.stderr)

    def test_applied_patch_history_created_only_after_success(self):
        history = self.history_path
        self.assertFalse(history.exists())
        cancelled = self.invoke("2\nYES\nno\n")
        self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
        self.assertFalse(history.exists() and history.read_text().strip())
        result = self.invoke("3\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_history(real_branch=self.payload["feature_branch"])
        self.assertEqual(stat.S_IMODE(history.stat().st_mode), 0o600)

    def test_full_local_workflow_and_repeated_menu(self):
        result = self.invoke("2\nYES\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Patch applied", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])
        result = self.invoke("4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Canonical checks passed", result.stdout)
        result = self.invoke("5\nYES\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Commit and push verified", result.stdout)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        changed = command("git", "show", "--pretty=", "--name-only", "HEAD", cwd=self.root).stdout.splitlines()
        self.assertEqual(set(changed), {"existing.txt", "new.txt"})
        self.assertIn("Add new file.", command("git", "log", "-1", "--format=%B", cwd=self.root).stdout)
        self.assertIn("Create/find PR", self.invoke("0\n").stdout)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "pushed")
        self.assert_history(real_branch=self.payload["feature_branch"])
