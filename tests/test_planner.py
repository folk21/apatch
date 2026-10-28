"""FS-05 guarded local goals in disposable Git repositories."""

import json
import zipfile

from apatch_lib.patch_history import AppliedPatchHistory
from apatch_lib.state import read_state_snapshot
from tests._support import LocalGitFixture, command


class PlannerTests(LocalGitFixture):
    def test_preview_is_read_only_on_new_zip(self):
        stem = self.make_self_contained_zip()
        original_index = (self.root / ".git/index").read_bytes()
        original_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout
        original_config = self.project_config.read_bytes()
        result = self.invoke_zip("goal=COMMITTED", "planOnly=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PLAN COMMITTED: APL, BRN, CHK, CMT", result.stdout)
        self.assertIn("PREVIEW", result.stdout)
        self.assertFalse(self.state_path.exists())
        self.assertFalse((self.root / ".apatch/params.json").exists())
        self.assertFalse(self.log_path.exists())
        self.assertEqual((self.root / ".git/index").read_bytes(), original_index)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout,
                         original_head)
        self.assertEqual(self.project_config.read_bytes(), original_config)

    def test_preview_of_existing_checked_session_preserves_runtime_files(self):
        stem = self.make_self_contained_zip()
        checked = self.invoke_zip("goal=CHECKED", "skipApproves=true", selection=stem)
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        paths = (self.state_path, self.history_path,
                 self.root / ".apatch/params.json", self.root / ".git/index")
        before = {path: path.read_bytes() for path in paths}
        before_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        preview = self.invoke_zip("goal=COMMITTED", "planOnly=true", selection=stem)
        self.assertEqual(preview.returncode, 0, preview.stderr + preview.stdout)
        self.assertIn("PLAN COMMITTED: CMT", preview.stdout)
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         before_head)

    def test_goal_checked_stops_without_commit_or_remote_publication(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("goal=CHECKED", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GOAL CHECKED: SUCCESS", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current",
                                 cwd=self.root).stdout.strip(), self.payload["feature_branch"])
        self.assertEqual(command("git", "rev-parse", "HEAD",
                                 cwd=self.root).stdout.strip(), self.head)
        state = read_state_snapshot(self.state_path)
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["phase"], "verified")
        self.assertIn("guarded_verification", record)
        self.assertEqual(len(state["feature_sessions"]), 1)
        self.assertFalse(command("git", "ls-remote", "--heads", "origin",
                                 f"refs/heads/{self.payload['feature_branch']}",
                                 cwd=self.root).stdout)

    def test_goal_committed_runs_exact_guarded_check_and_local_commit(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("goal=COMMITTED", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GOAL COMMITTED: SUCCESS", result.stdout)
        self.assertNotEqual(command("git", "rev-parse", "HEAD",
                                    cwd=self.root).stdout.strip(), self.head)
        names = command("git", "show", "--pretty=format:", "--name-only", "HEAD",
                        cwd=self.root).stdout.splitlines()
        self.assertEqual(set(names), {"existing.txt", "new.txt"})
        state = read_state_snapshot(self.state_path)
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "committed")
        self.assertEqual(len(state["feature_sessions"]), 1)

    def test_new_zip_continues_a_committed_feature_session(self):
        first = self.make_self_contained_zip()
        initial = self.invoke_zip("goal=COMMITTED", "skipApproves=true", selection=first)
        self.assertEqual(initial.returncode, 0, initial.stderr + initial.stdout)
        previous_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        followup = self.make_followup_zip()
        preview = self.invoke_zip("goal=CHECKED", "intent=continue",
                                  "planOnly=true", selection=followup.stem)
        self.assertEqual(preview.returncode, 0, preview.stderr + preview.stdout)
        self.assertIn("PLAN CHECKED: APL, CHK", preview.stdout)
        continued = self.invoke_zip("goal=CHECKED", "intent=continue",
                                    "skipApproves=true", selection=followup.stem)
        self.assertEqual(continued.returncode, 0, continued.stderr + continued.stdout)
        self.assertNotIn("GOAL STEP: BRN", continued.stdout)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         previous_head)
        state = read_state_snapshot(self.state_path)
        self.assertEqual(len(state["feature_sessions"]), 1)
        self.assertEqual(len(next(iter(state["feature_sessions"].values()))[
            "patch_workflow_keys"]), 2)
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 2)

    def test_overlapping_uncommitted_followup_needs_manual_review(self):
        first = self.make_self_contained_zip()
        initial = self.invoke_zip("goal=CHECKED", "skipApproves=true", selection=first)
        self.assertEqual(initial.returncode, 0, initial.stderr + initial.stdout)
        followup = self.make_followup_zip()
        before = self.state_path.read_bytes()
        blocked = self.invoke_zip("goal=CHECKED", "intent=continue",
                                  "skipApproves=true", selection=followup.stem)
        self.assertEqual(blocked.returncode, 2, blocked.stderr + blocked.stdout)
        self.assertIn("overlaps changed paths", blocked.stderr + blocked.stdout)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertFalse((self.root / "second.txt").exists())

    def test_disjoint_uncommitted_zip_can_share_the_verified_session(self):
        first = self.make_self_contained_zip()
        initial = self.invoke_zip("goal=CHECKED", "skipApproves=true", selection=first)
        self.assertEqual(initial.returncode, 0, initial.stderr + initial.stdout)
        followup = self.make_followup_zip()
        metadata = {key: value for key, value in self.payload.items()
                    if key != "patch_sha256"}
        metadata["patch_file"] = followup.name
        with zipfile.ZipFile(followup, "w") as archive:
            archive.writestr(f"{self.root.name}/second.txt", "second patch\n")
            archive.writestr(f"{self.root.name}/.apatch/params.json",
                             json.dumps(metadata))
        resumed = self.invoke_zip("goal=COMMITTED", "intent=continue",
                                  "skipApproves=true", selection=followup.stem)
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        self.assertIn("GOAL COMMITTED: SUCCESS", resumed.stdout)
        committed = command("git", "show", "--pretty=format:", "--name-only",
                            "HEAD", cwd=self.root).stdout.splitlines()
        self.assertEqual(set(committed), {"existing.txt", "new.txt", "second.txt"})

    def test_committed_goal_is_idempotent_without_repeating_commit(self):
        first = self.make_self_contained_zip()
        initial = self.invoke_zip("goal=COMMITTED", "skipApproves=true", selection=first)
        self.assertEqual(initial.returncode, 0, initial.stderr + initial.stdout)
        before = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        second = self.invoke_zip("goal=COMMITTED", "skipApproves=true", selection=first)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertIn("ALREADY_SATISFIED", second.stdout)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         before)

    def test_checked_then_committed_resumes_without_reapplying_zip(self):
        stem = self.make_self_contained_zip()
        checked = self.invoke_zip("goal=CHECKED", "skipApproves=true", selection=stem)
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        committed = self.invoke_zip("goal=COMMITTED", "skipApproves=true", selection=stem)
        self.assertEqual(committed.returncode, 0, committed.stderr + committed.stdout)
        self.assertNotIn("GOAL STEP: APL", committed.stdout)
        self.assertNotIn("GOAL STEP: CHK", committed.stdout)
        self.assertIn("GOAL STEP: CMT", committed.stdout)
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 1)

    def test_unclassified_manual_file_blocks_before_index_mutation(self):
        stem = self.make_self_contained_zip()
        checked = self.invoke_zip("goal=CHECKED", "skipApproves=true", selection=stem)
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        (self.root / "unknown.txt").write_text("developer owned\n")
        before_index = (self.root / ".git/index").read_bytes()
        before_state = self.state_path.read_bytes()
        denied = self.invoke_zip("goal=COMMITTED", "skipApproves=true", selection=stem)
        self.assertEqual(denied.returncode, 2, denied.stderr + denied.stdout)
        self.assertIn("Unclassified commit paths", denied.stdout + denied.stderr)
        self.assertEqual((self.root / ".git/index").read_bytes(), before_index)
        self.assertEqual(self.state_path.read_bytes(), before_state)
        self.assertEqual((self.root / "unknown.txt").read_text(), "developer owned\n")

    def test_missing_check_command_reports_root_and_config(self):
        stem = self.make_self_contained_zip()
        self.project_config.write_text(
            'schema_version: 1\nchecks:\n  - ["./missing-check.sh"]\n')
        denied = self.invoke_zip("goal=CHECKED", "skipApproves=true", selection=stem)
        self.assertEqual(denied.returncode, 2, denied.stderr + denied.stdout)
        self.assertIn("MISSING_CHECK_EXECUTABLE", denied.stdout)
        self.assertIn(str(self.root), denied.stdout)
        self.assertIn("config.yaml", denied.stdout)
        self.assertFalse((self.root / "new.txt").exists())

    def test_goal_rejects_conflicts_and_remote_goals(self):
        stem = self.make_self_contained_zip()
        cases = (
            ("goal=PUSHED",),
            ("goal=CHECKED", "op=CHK"),
            ("goal=CHECKED", "opSeq=APL,BRN"),
            ("goal=CHECKED", "handoffSeq=some.zip"),
            ("goal=CHECKED", "followup=true"),
            ("goal=CHECKED", "--strict"),
            ("goal=CHECKED", "--force"),
            ("intent=continue",),
            ("planOnly=true",),
        )
        for args in cases:
            with self.subTest(args=args):
                result = self.invoke_zip(*args, selection=stem)
                self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertFalse(self.state_path.exists())

    def test_goal_checked_repeated_does_not_recheck_or_reapply(self):
        stem = self.make_self_contained_zip()
        checked = self.invoke_zip("goal=CHECKED", "skipApproves=true", selection=stem)
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        before_state = self.state_path.read_bytes()
        before_history = self.history_path.read_bytes()
        result = self.invoke_zip("goal=CHECKED", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("ALREADY_SATISFIED", result.stdout)
        self.assertEqual(self.state_path.read_bytes(), before_state)
        self.assertEqual(self.history_path.read_bytes(), before_history)

    def test_goal_preserves_deterministic_opseq(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN,CHK", "skipApproves=true",
                                 selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("SEQUENCE RESULT: SUCCESS", result.stdout)
        self.assertFalse(read_state_snapshot(self.state_path).get("feature_sessions"))
