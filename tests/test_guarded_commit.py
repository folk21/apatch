"""FS-04 exact commit authorization against disposable local Git repositories."""

from dataclasses import replace

from unittest.mock import patch

from apatch_lib.commit_scope import (NeedsVerification, WaitingForUser,
                                     inspect_commit_scope)
from apatch_lib.context import inspect_guarded_commit_readiness
from apatch_lib.model import Abort, load_config, load_project_config
from apatch_lib.patch import handoff_from_zip
from apatch_lib.state import locked_state, read_state_snapshot
from apatch_lib.workflow import Workflow
from tests._support import LocalGitFixture, command


class GuardedCommitTests(LocalGitFixture):
    def config(self):
        return load_project_config(self.root, load_config(self.bin))

    def prepared(self):
        first = self.make_self_contained_zip()
        initial = self.invoke_zip("opSeq=APL,BRN,CHK,CMT", "skipApproves=true",
                                  selection=first)
        self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
        with locked_state(self.state_path) as state:
            workflow = Workflow(self.root, self.config(),
                                handoff_from_zip(self.config(), self.root, self.zip.name),
                                state, loose=True, skip_previous_cycles=True)
            session = workflow.create_session()
            workflow.attach_session(session.session_id)
        return session.session_id

    def followup(self, session_id, **kwargs):
        new = self.make_followup_zip(**kwargs)
        with locked_state(self.state_path) as state:
            workflow = Workflow(self.root, self.config(),
                                handoff_from_zip(self.config(), self.root, new.name),
                                state, loose=True, zip_selected=True, skip_previous_cycles=True)
            with patch("apatch_lib.loose.confirm", return_value=True):
                self.assertEqual(workflow.apply_session_zip(session_id), "SUCCESS")
        return new

    def with_workflow(self, new, action):
        with locked_state(self.state_path) as state:
            workflow = Workflow(self.root, self.config(),
                                handoff_from_zip(self.config(), self.root, new.name),
                                state, loose=True, skip_previous_cycles=True)
            return action(workflow)

    def test_guarded_check_and_commit_exact_patch_scope(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        original_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))
        changed = command("git", "diff-tree", "--no-commit-id", "--name-only",
                          "-r", "HEAD", cwd=self.root).stdout.splitlines()
        self.assertEqual(set(changed), {"existing.txt", "second.txt"})
        head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.assertNotEqual(head, original_head)
        state = read_state_snapshot(self.state_path)
        self.assertIn(head, state["feature_sessions"][session_id]["commit_shas"])
        self.assertFalse(command("git", "status", "--porcelain", cwd=self.root).stdout)

    def test_unknown_untracked_path_blocks_before_staging(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        (self.root / "other.txt").write_text("manual\n")
        index_before = (self.root / ".git/index").read_bytes()
        with self.assertRaisesRegex(WaitingForUser, "Unclassified commit paths: other.txt"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        self.assertEqual((self.root / ".git/index").read_bytes(), index_before)
        self.assertEqual((self.root / "other.txt").read_text(), "manual\n")

    def test_unknown_staged_path_blocks_even_with_skip_approves(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        (self.root / "other.txt").write_text("manual staged\n")
        command("git", "add", "other.txt", cwd=self.root)
        index_before = (self.root / ".git/index").read_bytes()
        with self.assertRaisesRegex(WaitingForUser, "Unclassified commit paths"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        self.assertEqual((self.root / ".git/index").read_bytes(), index_before)

    def test_explicit_manual_path_can_join_a_reviewed_commit(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        (self.root / "other.txt").write_text("accepted manual\n")
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(
            session_id, accepted_manual_paths=("other.txt",)))
        self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))
        names = command("git", "show", "--pretty=format:", "--name-only",
                        "HEAD", cwd=self.root).stdout.splitlines()
        self.assertEqual(set(names), {"existing.txt", "second.txt", "other.txt"})

    def test_explicit_acceptance_must_match_a_current_changed_path(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        with self.assertRaisesRegex(Abort, "must exist"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_check(
                session_id, accepted_manual_paths=("not-present.txt",)))

    def test_preexisting_staged_path_requires_separate_acceptance(self):
        session_id = self.prepared()
        (self.root / "other.txt").write_text("pre-staged\n")
        command("git", "add", "other.txt", cwd=self.root)
        new = self.followup(session_id)
        with self.assertRaisesRegex(WaitingForUser, "Unclassified commit paths"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(
            session_id, accepted_manual_paths=("other.txt",)))
        self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))
        self.assertFalse(command("git", "status", "--porcelain", cwd=self.root).stdout)

    def test_guarded_commit_requires_a_guarded_check(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        with self.assertRaisesRegex(NeedsVerification, "guarded CHK"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))

    def test_file_edit_after_check_requires_reverification(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        (self.root / "existing.txt").write_text("changed after CHK\n")
        with self.assertRaisesRegex(NeedsVerification, "stale"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))

    def test_index_change_after_check_requires_reverification(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        (self.root / "other.txt").write_text("new staged file\n")
        command("git", "add", "other.txt", cwd=self.root)
        with self.assertRaises(WaitingForUser):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))

    def test_policy_config_change_requires_reverification(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        self.project_config.write_text(self.project_config.read_text() + "\n")
        with self.assertRaises(WaitingForUser):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))

    def test_effective_idle_timeout_change_requires_reverification(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))

        def altered_commit(workflow):
            workflow.config = replace(workflow.config, check_idle_timeout_seconds=60)
            return workflow.loose_actions.guarded_commit(session_id)

        with self.assertRaises(NeedsVerification):
            self.with_workflow(new, altered_commit)

    def test_branch_drift_refuses_commit(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        command("git", "switch", "-c", "feature/wrong", cwd=self.root)
        with self.assertRaisesRegex(Abort, "branch, base, or remote"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))

    def test_remote_drift_refuses_commit(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        command("git", "remote", "set-url", "origin", str(self.base / "other.git"),
                cwd=self.root)
        with self.assertRaisesRegex(Abort, "branch, base, or remote"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))

    def test_checks_that_format_files_need_a_stable_second_run(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        script = self.root / "format_once.py"
        script.write_text(
            "from pathlib import Path\n"
            "p = Path('existing.txt')\n"
            "if p.read_text() != 'formatted\\n':\n"
            "    p.write_text('formatted\\n')\n")
        self.project_config.write_text(
            'schema_version: 1\nchecks:\n'
            '  - ["python3", "format_once.py"]\n')
        with self.assertRaisesRegex(Abort, "CHECKS_CHANGED_WORKTREE"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_check(
                session_id, accepted_manual_paths=(".apatch/config.yaml", "format_once.py")))
        with self.assertRaises(NeedsVerification):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(
            session_id, accepted_manual_paths=(".apatch/config.yaml", "format_once.py")))
        self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))
        self.assertEqual((self.root / "existing.txt").read_text(), "formatted\n")

    def test_bad_checks_never_authorize_a_commit(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        self.project_config.write_text('schema_version: 1\nchecks:\n  - ["false"]\n')
        with self.assertRaisesRegex(Abort, "Command failed"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_check(
                session_id, accepted_manual_paths=(".apatch/config.yaml",)))
        with self.assertRaises(NeedsVerification):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))

    def test_legacy_missing_footprint_refuses_unattended_commit(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        with locked_state(self.state_path) as state:
            key = state["feature_sessions"][session_id]["patch_workflow_keys"][-1]
            state["workflows"][key].pop("patch_footprint")
            from apatch_lib.state import save
            save(self.state_path, state)
        with self.assertRaisesRegex(WaitingForUser, "ownership was not recorded"):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))

    def test_untracked_source_becomes_staged_only_after_scope_validation(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        self.assertEqual(command("git", "status", "--porcelain",
                                 cwd=self.root).stdout.strip().splitlines(),
                         ["M  existing.txt", "A  second.txt"])

    def test_guarded_inspection_is_read_only(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        before_index = (self.root / ".git/index").read_bytes()
        before_state = self.state_path.read_bytes()
        scope = self.with_workflow(new, lambda w: inspect_commit_scope(w, session_id))
        self.assertEqual(set(scope.paths), {"existing.txt", "second.txt"})
        self.assertEqual((self.root / ".git/index").read_bytes(), before_index)
        self.assertEqual(self.state_path.read_bytes(), before_state)

    def test_manual_rename_is_not_automatically_authorized(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        command("git", "mv", "existing.txt", "renamed.txt", cwd=self.root)
        with self.assertRaises(WaitingForUser):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_check(
                session_id, accepted_manual_paths=("renamed.txt",)))

    def test_read_only_commit_readiness_distinguishes_three_states(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        before = self.with_workflow(new, lambda w:
                                    inspect_guarded_commit_readiness(w, session_id))
        self.assertEqual(before.status, "NEEDS_VERIFICATION")
        (self.root / "manual.txt").write_text("unknown\n")
        blocked = self.with_workflow(new, lambda w:
                                     inspect_guarded_commit_readiness(w, session_id))
        self.assertEqual(blocked.status, "WAITING_FOR_USER")
        (self.root / "manual.txt").unlink()
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        ready = self.with_workflow(new, lambda w: w.present_guarded_commit_readiness(session_id))
        self.assertEqual(ready.status, "READY")

    def test_deleted_owned_path_can_be_staged_and_committed(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        (self.root / "existing.txt").unlink()
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))
        self.assertFalse((self.root / "existing.txt").exists())
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")

    def test_interrupted_staging_retains_index_and_never_records_check(self):
        session_id = self.prepared()
        new = self.followup(session_id)
        from apatch_lib import loose
        real_run = loose.run

        def interrupt_after_add(args, cwd, **kwargs):
            result = real_run(args, cwd, **kwargs)
            if args[:2] == ["git", "add"]:
                raise Abort("Interrupted after staging")
            return result

        with patch("apatch_lib.loose.run", side_effect=interrupt_after_add):
            with self.assertRaisesRegex(Abort, "Interrupted after staging"):
                self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        self.assertIn("A  second.txt",
                      command("git", "status", "--porcelain", cwd=self.root).stdout)
        with self.assertRaises(NeedsVerification):
            self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))
        self.with_workflow(new, lambda w: w.loose_actions.guarded_check(session_id))
        self.with_workflow(new, lambda w: w.loose_actions.guarded_commit(session_id))
