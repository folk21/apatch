"""FS-03 session continuation after commit/push without changing legacy follow-up."""

from unittest.mock import patch

from apatch_lib.model import Abort, load_config, load_project_config
from apatch_lib.patch import handoff_from_zip
from apatch_lib.audit_collectors import local_git
from apatch_lib.session_continuation import require_session_continuation
from apatch_lib.state import locked_state, read_state_snapshot, save
from apatch_lib.workflow import Workflow
from tests._support import LocalGitFixture, command


class SessionContinuationTests(LocalGitFixture):
    def config(self):
        return load_project_config(self.root, load_config(self.bin))

    def prepare_session(self, *, pushed=False):
        first = self.make_self_contained_zip()
        applied = self.invoke_zip("opSeq=APL,BRN,CHK,CMT", "skipApproves=true",
                                  selection=first)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        if pushed:
            published = self.invoke_zip("op=PSH", "skipApproves=true")
            self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
        with locked_state(self.state_path) as state:
            workflow = Workflow(self.root, self.config(),
                                handoff_from_zip(self.config(), self.root, self.zip.name),
                                state, loose=True, skip_previous_cycles=True)
            session = workflow.create_session()
            workflow.attach_session(session.session_id)
        return session.session_id

    def apply_next(self, new_path, session_id):
        with locked_state(self.state_path) as state:
            workflow = Workflow(self.root, self.config(),
                                handoff_from_zip(self.config(), self.root, new_path.name),
                                state, loose=True, zip_selected=True,
                                skip_previous_cycles=True)
            with patch("apatch_lib.loose.confirm", return_value=True):
                result = workflow.apply_session_zip(session_id)
            return workflow, result

    def test_new_zip_after_commit_keeps_previous_commit_and_additive_history(self):
        session_id = self.prepare_session()
        prior_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        initial_history = self.history_path.read_bytes()
        new = self.make_followup_zip()
        workflow, result = self.apply_next(new, session_id)
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(workflow.phase, "patch_applied")
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "feature/test-local-handoff")
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), prior_head)
        self.assertEqual((self.root / "existing.txt").read_text(), "second revision\n")
        self.assertEqual((self.root / "second.txt").read_text(), "second patch\n")
        self.assertIn(initial_history, self.history_path.read_bytes())
        state = read_state_snapshot(self.state_path)
        session = state["feature_sessions"][session_id]
        self.assertEqual(len(session["patch_workflow_keys"]), 2)
        self.assertEqual(state["workflows"][session["patch_workflow_keys"][0]]["commit_sha"], prior_head)
        self.assertEqual(state["workflows"][session["patch_workflow_keys"][1]]["session_id"], session_id)

    def test_selected_newly_applied_zip_can_run_checks_and_commit_without_replaying(self):
        session_id = self.prepare_session()
        original_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        new = self.make_followup_zip()
        self.apply_next(new, session_id)
        continued = self.invoke_zip("opSeq=CHK,CMT,STS", "skipApproves=true",
                                    selection=new.stem)
        self.assertEqual(continued.returncode, 0, continued.stdout + continued.stderr)
        self.assertNotEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                            original_head)
        self.assertEqual(command("git", "rev-parse", "HEAD^", cwd=self.root).stdout.strip(),
                         original_head)
        state = read_state_snapshot(self.state_path)
        self.assertEqual(len(state["feature_sessions"][session_id]["patch_workflow_keys"]), 2)
        self.assertEqual(len(self.history_path.read_text().split("Date: ")) - 1, 2)

    def test_new_zip_after_push_keeps_published_revision(self):
        session_id = self.prepare_session(pushed=True)
        prior_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        new = self.make_followup_zip()
        _, result = self.apply_next(new, session_id)
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(command("git", "ls-remote", "--heads", "origin",
                                 "refs/heads/feature/test-local-handoff", cwd=self.root).stdout.split()[0],
                         prior_head)
        state = read_state_snapshot(self.state_path)
        first = state["workflows"][state["feature_sessions"][session_id]["patch_workflow_keys"][0]]
        self.assertEqual(first["pushed_sha"], prior_head)

    def test_open_pr_revision_is_verified_before_continuation(self):
        session_id = self.prepare_session(pushed=True)
        head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        state = read_state_snapshot(self.state_path)
        first_key = state["feature_sessions"][session_id]["patch_workflow_keys"][0]
        state["workflows"][first_key].update(phase="pr_created", pr_number=17)
        save(self.state_path, state)
        new = self.make_followup_zip()
        branch = "feature/test-local-handoff"
        pr = {"number": 17, "state": "OPEN", "headRefName": branch,
              "baseRefName": "main", "headRefOid": head}
        with patch("apatch_lib.session_continuation.remote_snapshot",
                   return_value=({branch: head}, [pr], True)):
            _, outcome = self.apply_next(new, session_id)
        self.assertEqual(outcome, "SUCCESS")
        saved = read_state_snapshot(self.state_path)["workflows"][first_key]
        self.assertEqual((saved["phase"], saved["pr_number"]), ("pr_created", 17))

    def test_truncated_or_mismatched_pr_blocks_without_a_new_checkpoint(self):
        session_id = self.prepare_session(pushed=True)
        state = read_state_snapshot(self.state_path)
        first_key = state["feature_sessions"][session_id]["patch_workflow_keys"][0]
        state["workflows"][first_key].update(phase="pr_created", pr_number=17)
        save(self.state_path, state)
        new = self.make_followup_zip()
        before_state, before_history = self.state_path.read_bytes(), self.history_path.read_bytes()
        with patch("apatch_lib.session_continuation.remote_snapshot",
                   return_value=({}, [], False)):
            with self.assertRaisesRegex(Abort, "live PR head"):
                self.apply_next(new, session_id)
        self.assertEqual(self.state_path.read_bytes(), before_state)
        self.assertEqual(self.history_path.read_bytes(), before_history)
        self.assertFalse((self.root / "second.txt").exists())

    def test_legacy_followup_after_commit_still_requires_uncommitted_predecessor(self):
        self.prepare_session()
        new = self.make_followup_zip()
        result = self.invoke_zip("op=APL", "followup=true", "skipApproves=true",
                                 selection=new.stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("previous uncommitted changes", result.stderr)
        self.assertFalse((self.root / "second.txt").exists())

    def test_modified_collision_blocks_before_history_or_source_writes(self):
        session_id = self.prepare_session()
        (self.root / "existing.txt").write_text("developer edit\n")
        new = self.make_followup_zip()
        original_state = self.state_path.read_bytes()
        original_history = self.history_path.read_bytes()
        with self.assertRaisesRegex(Abort, "overlaps locally modified paths: existing.txt"):
            self.apply_next(new, session_id)
        self.assertEqual((self.root / "existing.txt").read_text(), "developer edit\n")
        self.assertEqual(self.state_path.read_bytes(), original_state)
        self.assertEqual(self.history_path.read_bytes(), original_history)

    def test_staged_collision_preserves_existing_index(self):
        session_id = self.prepare_session()
        (self.root / "existing.txt").write_text("staged developer edit\n")
        command("git", "add", "existing.txt", cwd=self.root)
        original_index = (self.root / ".git/index").read_bytes()
        new = self.make_followup_zip()
        with self.assertRaisesRegex(Abort, "overlaps locally modified paths"):
            self.apply_next(new, session_id)
        self.assertEqual((self.root / ".git/index").read_bytes(), original_index)
        self.assertEqual((self.root / "existing.txt").read_text(), "staged developer edit\n")

    def test_remote_drift_during_confirmation_aborts_before_extraction(self):
        session_id = self.prepare_session()
        new = self.make_followup_zip()
        before_history = self.history_path.read_bytes()

        def remote_changes_during_confirmation(_question):
            command("git", "remote", "set-url", "origin", str(self.base / "different.git"),
                    cwd=self.root)
            return True

        with locked_state(self.state_path) as state:
            workflow = Workflow(self.root, self.config(),
                                handoff_from_zip(self.config(), self.root, new.name),
                                state, loose=True, zip_selected=True,
                                skip_previous_cycles=True)
            with patch("apatch_lib.loose.confirm", side_effect=remote_changes_during_confirmation):
                with self.assertRaisesRegex(Abort, "remote identity differs"):
                    workflow.apply_session_zip(session_id)
        self.assertEqual(self.history_path.read_bytes(), before_history)
        self.assertFalse((self.root / "second.txt").exists())

    def test_disjoint_manual_changes_remain_untouched(self):
        session_id = self.prepare_session()
        (self.root / "manual.txt").write_text("separate developer work\n")
        new = self.make_followup_zip()
        _, result = self.apply_next(new, session_id)
        self.assertEqual(result, "SUCCESS")
        self.assertEqual((self.root / "manual.txt").read_text(), "separate developer work\n")

    def test_remote_tip_drift_stops_before_new_application(self):
        session_id = self.prepare_session(pushed=True)
        new = self.make_followup_zip()
        with patch("apatch_lib.session_continuation._remote_feature_head",
                   return_value="f" * 40):
            with self.assertRaisesRegex(Abort, "published revision differs"):
                self.apply_next(new, session_id)
        self.assertFalse((self.root / "second.txt").exists())

    def test_branch_and_remote_identity_drift_are_rejected(self):
        session_id = self.prepare_session()
        new = self.make_followup_zip()
        command("git", "switch", "main", cwd=self.root)
        with self.assertRaisesRegex(Abort, "intended checked-out feature branch"):
            self.apply_next(new, session_id)
        command("git", "switch", "feature/test-local-handoff", cwd=self.root)
        command("git", "remote", "set-url", "origin", str(self.base / "moved.git"), cwd=self.root)
        with self.assertRaisesRegex(Abort, "remote identity differs"):
            self.apply_next(new, session_id)

    def test_ambiguous_active_session_owner_blocks_even_with_explicit_id(self):
        session_id = self.prepare_session()
        new = self.make_followup_zip()
        state = read_state_snapshot(self.state_path)
        another_id = "f" * 32
        duplicate = dict(state["feature_sessions"][session_id])
        duplicate.update(session_id=another_id, patch_workflow_keys=[],
                         observed_heads=[], commit_shas=[], pr_revisions=[])
        state["feature_sessions"][another_id] = duplicate
        save(self.state_path, state)
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(Abort, "ambiguous active feature-session owners"):
            self.apply_next(new, session_id)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_legacy_continuation_link_does_not_prove_current_predecessor(self):
        session_id = self.prepare_session()
        new = self.make_followup_zip()
        state = read_state_snapshot(self.state_path)
        first_key = state["feature_sessions"][session_id]["patch_workflow_keys"][0]
        state["workflows"][first_key]["continued_by"] = "unverified-missing-workflow"
        save(self.state_path, state)
        with self.assertRaisesRegex(Abort, "legacy continuation links"):
            self.apply_next(new, session_id)

    def test_unrecorded_manual_commit_is_not_accepted_as_session_head(self):
        session_id = self.prepare_session()
        (self.root / "manual.txt").write_text("manual revision\n")
        command("git", "add", "manual.txt", cwd=self.root)
        command("git", "commit", "-m", "Unrecorded commit", cwd=self.root)
        new = self.make_followup_zip()
        with self.assertRaisesRegex(Abort, "HEAD differs"):
            self.apply_next(new, session_id)

    def test_resolved_git_root_handles_symlinked_temporary_paths(self):
        session_id = self.prepare_session()
        new = self.make_followup_zip()
        alias = self.base / "repo-alias"
        alias.symlink_to(self.root, target_is_directory=True)

        def read_local_git(root, *args, **kwargs):
            if args == ("rev-parse", "--show-toplevel"):
                return str(alias) + "\n"
            return local_git(root, *args, **kwargs)

        with patch("apatch_lib.session_continuation.local_git", side_effect=read_local_git):
            _, result = self.apply_next(new, session_id)
        self.assertEqual(result, "SUCCESS")

    def test_invalid_explicit_session_id_is_rejected_before_mutation(self):
        self.prepare_session()
        new = self.make_followup_zip()
        original_state = self.state_path.read_bytes()
        with self.assertRaisesRegex(Abort, "valid explicit session ID"):
            self.apply_next(new, "unknown-session-id")
        self.assertEqual(self.state_path.read_bytes(), original_state)

    def test_duplicate_zip_and_missing_application_proof_are_rejected(self):
        session_id = self.prepare_session()
        first_handoff = handoff_from_zip(self.config(), self.root, self.zip.name)
        with self.assertRaisesRegex(Abort, "already applied ZIP"):
            require_session_continuation(self.root, self.config(), first_handoff, session_id)
        new = self.make_followup_zip()
        state = read_state_snapshot(self.state_path)
        prior_key = state["feature_sessions"][session_id]["patch_workflow_keys"][0]
        state["operation_runs"] = [run for run in state["operation_runs"]
                                   if run["workflow_key"] != prior_key or run["operation"]["number"] != 3]
        save(self.state_path, state)
        with self.assertRaisesRegex(Abort, "no successful journal proof"):
            self.apply_next(new, session_id)

    def test_interrupted_extraction_preserves_prior_commit_and_user_files(self):
        session_id = self.prepare_session()
        (self.root / "manual.txt").write_text("keep me\n")
        first_sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        new = self.make_followup_zip()
        with patch("apatch_lib.loose.apply", side_effect=Abort("simulated write failure")):
            with self.assertRaisesRegex(Abort, "simulated write failure"):
                self.apply_next(new, session_id)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), first_sha)
        self.assertEqual((self.root / "manual.txt").read_text(), "keep me\n")
        self.assertFalse((self.root / "second.txt").exists())
        self.assertEqual(len(read_state_snapshot(self.state_path)["feature_sessions"]
                             [session_id]["patch_workflow_keys"]), 1)
        self.assertEqual(len(self.history_path.read_text().split("Date: ")) - 1, 1)

    def test_post_application_link_failure_is_recoverable_without_reapplying(self):
        session_id = self.prepare_session()
        new = self.make_followup_zip()
        with patch.object(Workflow, "attach_session", side_effect=OSError("link unavailable")):
            with self.assertRaisesRegex(Abort, "link unavailable"):
                self.apply_next(new, session_id)
        state = read_state_snapshot(self.state_path)
        self.assertEqual(len(state["feature_sessions"][session_id]["patch_workflow_keys"]), 1)
        self.assertEqual(len(self.history_path.read_text().split("Date: ")) - 1, 2)
        self.assertEqual((self.root / "second.txt").read_text(), "second patch\n")
        with locked_state(self.state_path) as state:
            workflow = Workflow(self.root, self.config(),
                                handoff_from_zip(self.config(), self.root, new.name),
                                state, loose=True, skip_previous_cycles=True)
            linked = workflow.attach_session(session_id)
        self.assertEqual(len(linked.patch_workflow_keys), 2)
        self.assertEqual(len(self.history_path.read_text().split("Date: ")) - 1, 2)
