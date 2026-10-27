"""Read-only context classification across local Git and recorded session evidence."""

import json
from unittest.mock import patch

from apatch_lib.context import Scenario, inspect_context
from apatch_lib.model import load_config, load_project_config
from apatch_lib.patch import handoff_from_zip
from apatch_lib.session import create_feature_session
from apatch_lib.state import locked_state, save
from tests._support import LocalGitFixture, command


class ContextTests(LocalGitFixture):
    def config(self):
        return load_project_config(self.root, load_config(self.bin))

    def inspect(self, **kwargs):
        return inspect_context(self.root, self.config(), **kwargs)

    def applied_zip(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return handoff_from_zip(self.config(), self.root, self.zip.name)

    def test_new_base_is_local_candidate_not_unverified_remote_authorization(self):
        before_index = (self.root / ".git/index").read_bytes()
        before_config = self.project_config.read_bytes()
        before_refs = command("git", "show-ref", cwd=self.root).stdout
        result = self.inspect()
        self.assertEqual(result.scenario, Scenario.NEW_BASE)
        self.assertEqual(result.remote_coverage, "UNKNOWN")
        self.assertIn("BASE_REMOTE_UNVERIFIED", [item.code for item in result.findings])
        self.assertFalse(result.changed_paths)
        self.assertIsNone(result.session_id)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.lock_path.exists())
        self.assertFalse(self.log_path.exists())
        self.assertEqual((self.root / ".git/index").read_bytes(), before_index)
        self.assertEqual(self.project_config.read_bytes(), before_config)
        self.assertEqual(command("git", "show-ref", cwd=self.root).stdout, before_refs)

    def test_remote_base_synchronization_is_explicit_and_read_only(self):
        with patch("apatch_lib.context.remote_snapshot", side_effect=AssertionError("unexpected PR query")):
            verified = self.inspect(verify_remote=True)
        self.assertEqual(verified.scenario, Scenario.NEW_BASE)
        self.assertEqual(verified.remote_coverage, "VERIFIED")
        (self.root / "existing.txt").write_text("committed newer base\n")
        command("git", "add", "existing.txt", cwd=self.root)
        command("git", "commit", "-m", "new local base", cwd=self.root)
        behind = self.inspect(verify_remote=True)
        self.assertEqual(behind.scenario, Scenario.MANUAL_DRIFT)
        self.assertIn("BASE_NOT_SYNCHRONIZED", [item.code for item in behind.findings])

    def test_dirty_base_is_not_silently_classified_as_ready(self):
        (self.root / "manual.txt").write_text("manual addition\n")
        result = self.inspect()
        self.assertEqual(result.scenario, Scenario.MANUAL_DRIFT)
        self.assertEqual(result.changed_paths, ("manual.txt",))
        self.assertIn("DIRTY_BASE", [item.code for item in result.findings])

    def test_verified_selected_zip_ignores_different_cached_selection_without_writes(self):
        handoff = self.applied_zip()
        cache = self.root / ".apatch/params.json"
        stale_cache = json.loads(cache.read_text())
        stale_cache["patch_file"] = "a-different-cached-zip.zip"
        cache.write_text(json.dumps(stale_cache))
        saved = cache.read_bytes()
        state = self.state_path.read_bytes()
        history = self.history_path.read_bytes()
        refs = command("git", "show-ref", cwd=self.root).stdout
        result = self.inspect(handoff=handoff)
        self.assertEqual(result.scenario, Scenario.ALREADY_APPLIED_ZIP)
        self.assertEqual(result.selected_patch, self.zip.name)
        self.assertIn("APPLIED_ZIP", [item.code for item in result.findings])
        self.assertEqual(cache.read_bytes(), saved)
        self.assertEqual(self.state_path.read_bytes(), state)
        self.assertEqual(self.history_path.read_bytes(), history)
        self.assertEqual(command("git", "show-ref", cwd=self.root).stdout, refs)

    def test_active_uncommitted_and_new_followup_without_a_session(self):
        self.applied_zip()
        new = self.make_followup_zip()
        handoff = handoff_from_zip(self.config(), self.root, new.name)
        result = self.inspect(handoff=handoff)
        self.assertEqual(result.scenario, Scenario.ACTIVE_UNCOMMITTED)
        self.assertIn("UNCOMMITTED_PATCH", [item.code for item in result.findings])
        self.assertIsNone(result.session_id)

    def test_committed_and_unknown_remote_publication_are_distinct(self):
        self.applied_zip()
        checked = self.invoke_zip("op=CHK", "skipApproves=true")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        committed = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        result = self.inspect()
        self.assertEqual(result.scenario, Scenario.COMMITTED)
        self.assertIn("LOCAL_COMMIT", [item.code for item in result.findings])
        pushed = self.invoke_zip("op=PSH", "skipApproves=true")
        self.assertEqual(pushed.returncode, 0, pushed.stdout + pushed.stderr)
        offline = self.inspect()
        self.assertEqual(offline.scenario, Scenario.UNKNOWN_REMOTE)
        self.assertEqual(offline.remote_coverage, "UNKNOWN")
        self.assertIn("REMOTE_NOT_QUERIED", [item.code for item in offline.findings])

    def test_unexpected_manual_commit_does_not_inherit_previous_verification(self):
        self.applied_zip()
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        self.assertEqual(self.invoke_zip("op=CMT", "skipApproves=true").returncode, 0)
        (self.root / "new.txt").write_text("unrelated later change\n")
        command("git", "add", "new.txt", cwd=self.root)
        command("git", "commit", "-m", "Manual later work", cwd=self.root)
        drift = self.inspect()
        self.assertEqual(drift.scenario, Scenario.MANUAL_DRIFT)
        self.assertIn("COMMIT_DRIFT", [item.code for item in drift.findings])

    def test_pushed_branch_requires_verified_remote_head_and_pr_revision(self):
        self.applied_zip()
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        self.assertEqual(self.invoke_zip("op=CMT", "skipApproves=true").returncode, 0)
        self.assertEqual(self.invoke_zip("op=PSH", "skipApproves=true").returncode, 0)
        sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        branch = "feature/test-local-handoff"
        with patch("apatch_lib.context.remote_snapshot", return_value=({branch: sha}, [], True)):
            valid = self.inspect(verify_remote=True)
        self.assertEqual(valid.scenario, Scenario.PUSHED_OR_OPEN_PR)
        self.assertEqual(valid.remote_coverage, "VERIFIED")
        with patch("apatch_lib.context.remote_snapshot", return_value=({branch: "f" * 40}, [], True)):
            drift = self.inspect(verify_remote=True)
        self.assertEqual(drift.scenario, Scenario.MANUAL_DRIFT)
        with patch("apatch_lib.context.remote_snapshot", side_effect=ValueError("offline")):
            uncertain = self.inspect(verify_remote=True)
        self.assertEqual(uncertain.scenario, Scenario.UNKNOWN_REMOTE)
        self.assertEqual(uncertain.remote_coverage, "UNKNOWN")

        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        record["phase"] = "pr_created"
        record["pr_number"] = 13
        self.state_path.write_text(json.dumps(state))
        with patch("apatch_lib.context.remote_snapshot", return_value=({branch: sha}, [], True)):
            no_pr = self.inspect(verify_remote=True)
        self.assertEqual(no_pr.scenario, Scenario.BLOCKED)
        matching = {"number": 13, "state": "OPEN", "headRefName": branch,
                    "baseRefName": "main", "headRefOid": sha}
        with patch("apatch_lib.context.remote_snapshot", return_value=({branch: sha}, [matching], True)):
            valid_pr = self.inspect(verify_remote=True)
        self.assertEqual(valid_pr.scenario, Scenario.PUSHED_OR_OPEN_PR)
        with patch("apatch_lib.context.remote_snapshot", return_value=({branch: sha}, [matching], False)):
            truncated = self.inspect(verify_remote=True)
        self.assertEqual(truncated.scenario, Scenario.UNKNOWN_REMOTE)

    def test_missing_check_executable_detected_before_running_any_check(self):
        self.project_config.write_text('schema_version: 1\nchecks:\n  - ["./missing_checks.sh"]\n')
        before_config = self.project_config.read_bytes()
        with patch("apatch_lib.context.remote_snapshot", side_effect=AssertionError("unexpected remote query")):
            result = self.inspect()
        self.assertEqual(result.scenario, Scenario.MISSING_CHECKS)
        self.assertIn("./missing_checks.sh", result.findings[0].detail)
        self.assertEqual(self.project_config.read_bytes(), before_config)
        self.assertFalse(self.state_path.exists())

    def test_missing_remote_does_not_promote_local_evidence(self):
        command("git", "remote", "remove", "origin", cwd=self.root)
        result = self.inspect()
        self.assertEqual(result.scenario, Scenario.UNKNOWN_REMOTE)
        self.assertIn("CONFIGURED_REMOTE_UNAVAILABLE", [item.code for item in result.findings])
        self.assertFalse(self.state_path.exists())

    def test_detached_head_blocks_classification_without_changing_refs(self):
        command("git", "checkout", "--detach", cwd=self.root)
        before_refs = command("git", "show-ref", cwd=self.root).stdout
        result = self.inspect()
        self.assertEqual(result.scenario, Scenario.MANUAL_DRIFT)
        self.assertIn("DETACHED_HEAD", [item.code for item in result.findings])
        self.assertEqual(command("git", "show-ref", cwd=self.root).stdout, before_refs)

    def test_session_remote_identity_conflict_is_not_masked_by_branch(self):
        with locked_state(self.state_path) as state:
            item = create_feature_session(
                state, root=self.root, remote_name="origin",
                remote_url=str(self.remote), base_branch="main",
                feature_branch="feature/test-local-handoff")
            save(self.state_path, state)
        command("git", "remote", "set-url", "origin", str(self.base / "other-remote.git"), cwd=self.root)
        handoff = handoff_from_zip(self.config(), self.root, self.make_self_contained_zip() + ".zip")
        before = self.state_path.read_bytes()
        result = self.inspect(handoff=handoff, session_id=item.session_id)
        self.assertEqual(result.scenario, Scenario.MANUAL_DRIFT)
        self.assertIn("SESSION_REMOTE_DRIFT", [item.code for item in result.findings])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_explicit_session_identity_must_match_branch_and_status(self):
        exclude = self.root / ".git/info/exclude"
        exclude.write_text(exclude.read_text() +
                           "\n/.apatch/apply_patch.state.json\n"
                           "/.apatch/apply_patch.state.json.lock\n")
        with locked_state(self.state_path) as state:
            item = create_feature_session(
                state, root=self.root, remote_name="origin",
                remote_url=str(self.remote), base_branch="main",
                feature_branch="feature/test-local-handoff")
            save(self.state_path, state)
        stem = self.make_self_contained_zip()
        handoff = handoff_from_zip(self.config(), self.root, stem + ".zip")
        found = self.inspect(handoff=handoff, session_id=item.session_id)
        self.assertEqual(found.scenario, Scenario.NEW_BASE)
        self.assertEqual(found.session_id, item.session_id)
        unknown = self.inspect(handoff=handoff, session_id="f" * 32)
        self.assertEqual(unknown.scenario, Scenario.BLOCKED)
        self.assertIn("SESSION_MISMATCH", [item.code for item in unknown.findings])

    def test_historical_continuation_is_weak_evidence_without_replay(self):
        handoff = self.applied_zip()
        saved = json.loads(self.state_path.read_text())
        next(iter(saved["workflows"].values()))["superseded_by"] = "other-patch"
        self.state_path.write_text(json.dumps(saved))
        before = self.state_path.read_bytes()
        result = self.inspect(handoff=handoff)
        self.assertEqual(result.scenario, Scenario.AMBIGUOUS)
        self.assertIn("HISTORICAL_CONTINUATION", [item.code for item in result.findings])
        self.assertEqual(self.state_path.read_bytes(), before)
