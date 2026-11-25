"""Check threshold enforcement across local commits and publication boundaries."""

from dataclasses import replace
from unittest.mock import patch

from tests._support import LocalGitFixture, command, json, load_config, load_project_config, unittest
from apatch_lib.check_gates import require_boundary
from apatch_lib.mo_core.api import Abort
from apatch_lib.mo_handoff.api import load_handoff
from apatch_lib.state import read_state_snapshot
from apatch_lib.workflow import Workflow


class CheckBoundaryTests(LocalGitFixture):
    def configure_boundary(self, boundary="MRG"):
        self.project_config.write_text(
            'schema_version: 1\n'
            'checks:\n  - ["./run_checks.sh"]\n'
            f'disabled_without_chk: {boundary}\n')
        command("git", "add", ".apatch/config.yaml", cwd=self.root)
        command("git", "commit", "-m", "Configure check boundary", cwd=self.root)
        command("git", "push", "origin", "main", cwd=self.root)
        self.head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.payload["base_commit"] = self.head

    def ready(self):
        selected = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN", "skipApproves=true", selection=selected)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def active_workflow(self, *, boundary=None):
        config = load_project_config(self.root, load_config(self.bin))
        if boundary is not None:
            config = replace(config, disabled_without_chk=boundary)
        state = read_state_snapshot(config.state_path)
        handoff = load_handoff(self.params)
        return Workflow(self.root, config, handoff, state, loose=True, skip_previous_cycles=True)

    def test_default_blocks_cmt_and_chk_unblocks(self):
        self.ready()
        blocked = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("CHECK_GATE_CMT", blocked.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        committed = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        self.assertNotIn("unchecked_commit_sha", self.active_workflow().record)

    def test_mrg_policy_can_commit_and_push_without_chk_but_merge_needs_final_check(self):
        self.configure_boundary()
        self.ready()
        committed = self.invoke_zip("opSeq=CMT,PSH,STS", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        self.assertNotIn("CANONICAL CHECK PASS", committed.stdout)
        w = self.active_workflow()
        self.assertEqual(w.record["unchecked_commit_sha"],
                         command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip())
        with self.assertRaisesRegex(Abort, "CHECK_GATE_MRG"):
            require_boundary(w, "MRG")
        checked = self.invoke_zip("op=CHK", "skipApproves=true")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        w = self.active_workflow()
        self.assertEqual(w.record["verified_commit"],
                         command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip())
        require_boundary(w, "MRG")
        w.config = replace(w.config, disabled_without_chk="CMT")
        require_boundary(w, "MRG")

    def test_deferred_commit_handles_rename_detected_only_after_staging(self):
        self.configure_boundary()
        self.ready()
        (self.root / "existing.txt").rename(self.root / "moved.txt")
        before = command("git", "status", "--short", cwd=self.root).stdout
        self.assertIn(" D existing.txt", before)
        self.assertIn("?? moved.txt", before)

        committed = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        self.assertNotIn("COMMIT_CONTENT_DRIFT", committed.stderr)
        self.assertEqual((self.root / "moved.txt").read_text(), "updated\n")
        self.assertFalse((self.root / "existing.txt").exists())
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        files = command("git", "ls-tree", "-r", "--name-only", "HEAD", cwd=self.root).stdout
        self.assertIn("moved.txt", files.splitlines())
        self.assertNotIn("existing.txt", files.splitlines())
        self.assertEqual(self.active_workflow().record["unchecked_commit_sha"],
                         command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip())

    def test_unfolded_status_detects_staged_rename_scope(self):
        from apatch_lib.mo_git.repository import status_paths

        command("git", "mv", "existing.txt", "renamed.txt", cwd=self.root)
        default = status_paths(self.root)
        unfolded = status_paths(self.root, detect_renames=False)
        self.assertIn("renamed.txt", default)
        self.assertEqual(set(unfolded), {"existing.txt", "renamed.txt"})

    def test_commit_still_blocks_worktree_race_during_staging(self):
        from apatch_lib import loose
        from apatch_lib.mo_presentation.confirmation import reset_skip_approvals, set_skip_approvals

        self.configure_boundary()
        self.ready()
        before_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        workflow = self.active_workflow()
        original_run = loose.run

        def injected_run(argv, root, **kwargs):
            result = original_run(argv, root, **kwargs)
            if argv == ["git", "add", "-A"]:
                (self.root / "new.txt").write_text("concurrent edit\n")
            return result

        token = set_skip_approvals(True)
        try:
            with patch.object(loose, "run", side_effect=injected_run):
                with self.assertRaisesRegex(Abort, "COMMIT_CONTENT_DRIFT"):
                    workflow.loose_actions.commit()
        finally:
            reset_skip_approvals(token)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         before_head)
        self.assertEqual((self.root / "new.txt").read_text(), "concurrent edit\n")

    def test_commit_still_blocks_index_race_during_staging(self):
        from apatch_lib import loose
        from apatch_lib.mo_presentation.confirmation import reset_skip_approvals, set_skip_approvals

        self.configure_boundary()
        self.ready()
        before_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        workflow = self.active_workflow()
        original_run = loose.run

        def injected_run(argv, root, **kwargs):
            result = original_run(argv, root, **kwargs)
            if argv == ["git", "add", "-A"]:
                # Use a known tracked blob to introduce index-only drift.
                old = command("git", "rev-parse", "HEAD:existing.txt", cwd=self.root).stdout.strip()
                command("git", "update-index", "--cacheinfo", "100644", old,
                        "new.txt", cwd=self.root)
            return result

        token = set_skip_approvals(True)
        try:
            with patch.object(loose, "run", side_effect=injected_run):
                with self.assertRaisesRegex(Abort, "COMMIT_CONTENT_DRIFT"):
                    workflow.loose_actions.commit()
        finally:
            reset_skip_approvals(token)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         before_head)
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")

    def test_explicit_cli_override_is_not_persistent_and_records_unchecked_history(self):
        self.ready()
        committed = self.invoke_zip("op=CMT", "disabledWithoutChk=MRG", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        w = self.active_workflow()
        self.assertEqual(w.config.disabled_without_chk, "CMT")
        self.assertIn("unchecked_commit_sha", w.record)
        with self.assertRaisesRegex(Abort, "CHECK_GATE_MRG"):
            require_boundary(w, "MRG")

    def test_psh_policy_blocks_push_until_postcommit_chk(self):
        self.configure_boundary("PSH")
        self.ready()
        self.assertEqual(self.invoke_zip("op=CMT", "skipApproves=true").returncode, 0)
        blocked = self.invoke_zip("op=PSH", "skipApproves=true")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("CHECK_GATE_PSH", blocked.stderr)
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        pushed = self.invoke_zip("op=PSH", "skipApproves=true")
        self.assertEqual(pushed.returncode, 0, pushed.stdout + pushed.stderr)

    def test_policy_rejects_invalid_values_and_disallowed_modes(self):
        for entry in ('disabled_without_chk: SYN', 'disabled_without_chk: false',
                      'disabled_without_chk: [MRG]'):
            with self.subTest(entry=entry):
                self.project_config.write_text('schema_version: 1\nchecks:\n'
                                               '  - ["./run_checks.sh"]\n' + entry + '\n')
                result = self.invoke_zip("op=STS")
                self.assertEqual(result.returncode, 2)
                self.assertIn("disabled_without_chk", result.stderr)
        self.configure_boundary()
        for args in (("--force", "op=CMT"), ("--strict", "op=CMT"),
                     ("goal=COMMITTED",)):
            with self.subTest(args=args):
                result = self.invoke_zip(*args, "disabledWithoutChk=MRG")
                self.assertEqual(result.returncode, 2)
                self.assertIn("disabledWithoutChk", result.stderr)

    def test_commit_gate_rejects_changed_worktree_after_chk(self):
        self.ready()
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        (self.root / "existing.txt").write_text("changed again\n")
        result = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("CHECK_GATE_CMT", result.stderr)

    def test_merge_gate_rechecks_final_head_and_policy_before_github(self):
        self.configure_boundary()
        self.ready()
        self.assertEqual(self.invoke_zip("op=CMT", "skipApproves=true").returncode, 0)
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        workflow = self.active_workflow()
        with patch.object(workflow.force_actions, "_recover_pr",
                          return_value=(workflow.handoff, {"state": "CLOSED"}, "repo")) as recover:
            workflow.force_actions.merge()
            recover.assert_called_once()
        command("git", "commit", "--allow-empty", "-m", "unexpected new commit", cwd=self.root)
        workflow = self.active_workflow()
        with patch.object(workflow.force_actions, "_recover_pr") as recover:
            with self.assertRaisesRegex(Abort, "CHECK_GATE_MRG"):
                workflow.force_actions.merge()
            recover.assert_not_called()

    def test_unchecked_commit_on_base_is_rejected_even_when_relaxed(self):
        self.configure_boundary()
        (self.root / "existing.txt").write_text("manual edit\n")
        result = self.invoke_cli("op=CMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("CHECK_GATE_UNCHECKED_COMMIT", result.stderr)

    def test_pushed_feature_allows_explicit_followup_without_replaying_zip(self):
        self.configure_boundary()
        self.ready()
        committed = self.invoke_zip("opSeq=CMT,PSH", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        second = self.make_followup_zip()
        result = self.invoke_zip("op=APL", "followup=true", "skipApproves=true",
                                 selection=second.stem)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), sha)
        self.assertEqual((self.root / "second.txt").read_text(), "second patch\n")

    def test_open_pr_followup_requires_exact_live_identity(self):
        from apatch_lib.mo_handoff.inspection import handoff_from_zip
        from apatch_lib.session_continuation import require_committed_loose_followup

        self.configure_boundary()
        self.ready()
        self.assertEqual(self.invoke_zip("opSeq=CMT,PSH", "skipApproves=true").returncode, 0)
        current = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        data = json.loads(self.state_path.read_text())
        previous = next(iter(data["workflows"].values()))
        previous.update(phase="pr_created", pr_number=77)
        self.state_path.write_text(json.dumps(data))
        second = self.make_followup_zip()
        config = self.active_workflow().config
        handoff = handoff_from_zip(config, self.root, second.name)
        pr = {"number": 77, "state": "OPEN", "headRefName": self.payload["feature_branch"],
              "baseRefName": "main", "headRefOid": current}
        with patch("apatch_lib.session_continuation.remote_snapshot",
                   return_value=({self.payload["feature_branch"]: current}, [pr], True)):
            key = require_committed_loose_followup(self.root, config, handoff,
                                                    read_state_snapshot(self.state_path))
            self.assertEqual(key, next(iter(data["workflows"])))
        with patch("apatch_lib.session_continuation.remote_snapshot",
                   return_value=({self.payload["feature_branch"]: current},
                                 [{**pr, "headRefOid": "a" * 40}], True)):
            with self.assertRaisesRegex(Abort, "verified open PR"):
                require_committed_loose_followup(self.root, config, handoff,
                                                  read_state_snapshot(self.state_path))

    def test_pr_boundary_blocks_before_remote_lookup(self):
        self.configure_boundary("PR")
        self.ready()
        self.assertEqual(self.invoke_zip("opSeq=CMT,PSH", "skipApproves=true").returncode, 0)
        workflow = self.active_workflow()
        with patch.object(workflow.force_actions, "_ensure_pushed") as remote:
            with self.assertRaisesRegex(Abort, "CHECK_GATE_PR"):
                workflow.force_actions.pr()
            remote.assert_not_called()
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        require_boundary(self.active_workflow(), "PR")

    def test_failed_git_commit_preserves_premerge_check_obligation(self):
        self.configure_boundary()
        self.ready()
        hook = self.root / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        failed = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(failed.returncode, 2)
        workflow = self.active_workflow()
        self.assertTrue(workflow.record["unchecked_pending"])
        with self.assertRaisesRegex(Abort, "CHECK_GATE_MRG"):
            require_boundary(workflow, "MRG")
        hook.unlink()
        committed = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        self.assertIn("unchecked_commit_sha", self.active_workflow().record)

    def test_strict_keeps_its_existing_check_before_commit_contract(self):
        self.configure_boundary()
        self.ready()
        workflow = self.active_workflow()
        workflow.loose = False
        workflow.force = False
        require_boundary(workflow, "CMT")
        require_boundary(workflow, "PSH")
        require_boundary(workflow, "PR")
        require_boundary(workflow, "MRG")
        workflow.state["workflows"][workflow.key]["unchecked_pending"] = True
        with self.assertRaisesRegex(Abort, "CHECK_GATE_MRG"):
            require_boundary(workflow, "MRG")

    def test_final_chk_before_commit_attests_exact_tree_for_merge(self):
        self.configure_boundary()
        self.ready()
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        committed = self.invoke_zip("opSeq=CMT,PSH", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        workflow = self.active_workflow()
        self.assertEqual(workflow.record.get("verified_commit"),
                         command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip())
        require_boundary(workflow, "MRG")
        command("git", "commit", "--allow-empty", "-m", "post-check drift", cwd=self.root)
        with self.assertRaisesRegex(Abort, "CHECK_GATE_MRG"):
            require_boundary(self.active_workflow(), "MRG")

    def test_final_verified_commit_covers_prior_unchecked_feature_commit(self):
        self.configure_boundary()
        self.ready()
        initial = self.invoke_zip("opSeq=CMT,PSH", "skipApproves=true")
        self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
        second = self.make_followup_zip()
        applied = self.invoke_zip("op=APL", "followup=true", "skipApproves=true",
                                  selection=second.stem)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        final = self.invoke_zip("opSeq=CMT,PSH", "skipApproves=true")
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
        from apatch_lib.mo_handoff.inspection import handoff_from_zip
        config = load_project_config(self.root, load_config(self.bin))
        state = read_state_snapshot(config.state_path)
        handoff = handoff_from_zip(config, self.root, second.name)
        workflow = Workflow(self.root, config, handoff, state,
                            loose=True, skip_previous_cycles=True)
        self.assertEqual(workflow.record["verified_commit"],
                         command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip())
        self.assertTrue(any(item.get("unchecked_pending") for item in
                            workflow.state["workflows"].values()))
        require_boundary(workflow, "MRG")
