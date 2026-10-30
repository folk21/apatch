"""Pending ZIP branch reassignment must preserve application and Git evidence."""

import hashlib
import json
import zipfile

from tests._support import LocalGitFixture, command


class PendingZipBranchReassignmentTests(LocalGitFixture):
    TARGET = "feature/macos-runner-phase-compat"

    def prepare_pending(self):
        parameters = {key: value for key, value in self.payload.items()
                      if key != "patch_sha256"}
        with zipfile.ZipFile(self.zip, "w") as archive:
            for name, contents in (("existing.txt", "updated\n"),
                                   ("new.txt", "new\n"),
                                   ("third.txt", "third\n"),
                                   ("fourth.txt", "fourth\n")):
                archive.writestr(f"{self.root.name}/{name}", contents)
            archive.writestr(f"{self.root.name}/.apatch/params.json", json.dumps(parameters))
        applied = self.invoke_zip(self.zip.stem, "op=APL", "skipApproves=true")
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(len(record["changed_paths"]), 4)
        return record

    def test_reassign_existing_planned_branch_and_resume_fmt_chk(self):
        original = self.prepare_pending()
        original_sha = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        before_history = self.history_path.read_text()
        before_cache = (self.root / ".apatch/params.json").read_bytes()
        command("git", "branch", "feature/test-local-handoff", cwd=self.root)
        command("git", "switch", "feature/test-local-handoff", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "unmerged old branch work", cwd=self.root)
        command("git", "switch", "main", cwd=self.root)

        blocked = self.invoke_zip("op=BRN", "skipApproves=true")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("already exists", blocked.stderr + blocked.stdout)
        selected = self.invoke_zip("op=BRN", f"featureBranch={self.TARGET}",
                                   "skipApproves=true")
        self.assertEqual(selected.returncode, 0, selected.stderr + selected.stdout)
        self.assertIn("Pending ZIP reassigned", selected.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.TARGET)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)
        self.assertEqual((self.root / ".apatch/params.json").read_bytes(), before_cache)
        self.assertTrue(command("git", "show-ref", "--verify", "refs/heads/feature/test-local-handoff",
                                cwd=self.root).stdout)
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["changed_paths"], original["changed_paths"])
        self.assertEqual(record["archive_sha256"], original_sha)
        self.assertEqual(record["before_patch_head"], self.head)
        self.assertEqual(record["reassigned_branch"], self.TARGET)
        self.assertEqual(record["source_branch"], "feature/test-local-handoff")
        self.assertEqual(state["operation_runs"][0]["operation"]["number"], 3)
        self.assertEqual(sum(1 for r in state["operation_runs"] if r["operation"]["number"] == 3), 1)
        self.assertIn("Planned feature branch: feature/test-local-handoff", self.history_path.read_text())
        self.assertIn(f"Real feature branch: {self.TARGET}", self.history_path.read_text())
        self.assertNotEqual(self.history_path.read_text(), before_history)

        self.project_config.write_text(self.project_config.read_text() +
                                       'format_commands:\n  - ["git", "diff", "--check"]\n')
        resumed = self.invoke_zip("opSeq=FMT,CHK,STS", "skipApproves=true")
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        self.assertIn("Canonical checks passed", resumed.stdout)
        self.assertEqual(json.loads(self.state_path.read_text())["workflows"][
            next(iter(state["workflows"]))]["phase"], "verified")

    def test_target_local_or_remote_collision_does_not_mutate_checkpoint(self):
        self.prepare_pending()
        prior_state = self.state_path.read_bytes()
        prior_history = self.history_path.read_bytes()
        command("git", "branch", self.TARGET, cwd=self.root)
        collision = self.invoke_zip("op=BRN", f"featureBranch={self.TARGET}",
                                    "skipApproves=true")
        self.assertEqual(collision.returncode, 2)
        self.assertIn("exists locally", collision.stderr)
        self.assertEqual(self.state_path.read_bytes(), prior_state)
        command("git", "branch", "-d", self.TARGET, cwd=self.root)
        command("git", "push", "origin", f"HEAD:refs/heads/{self.TARGET}", cwd=self.root)
        collision = self.invoke_zip("op=BRN", f"featureBranch={self.TARGET}",
                                    "skipApproves=true")
        self.assertEqual(collision.returncode, 2)
        self.assertIn("exists on origin", collision.stderr)
        self.assertEqual(self.state_path.read_bytes(), prior_state)
        self.assertEqual(self.history_path.read_bytes(), prior_history)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "main")

    def test_reassign_requires_pending_applied_zip_and_safe_action(self):
        self.make_self_contained_zip()
        for options in (("op=APL",), ("goal=CHECKED",), ("op=CHK",),
                        ("--force", "op=BRN"), ("opSeq=APL,BRN",)):
            with self.subTest(options=options):
                result = self.invoke_zip(*options, f"featureBranch={self.TARGET}",
                                         "skipApproves=true")
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.state_path.exists())
        result = self.invoke_zip(self.zip.stem, "op=BRN", f"featureBranch={self.TARGET}",
                                 "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("BRN is only allowed to recover", result.stderr + result.stdout)

    def test_explicit_zip_resume_after_reassignment_preserves_source_provenance(self):
        self.prepare_pending()
        result = self.invoke_zip("op=BRN", f"featureBranch={self.TARGET}",
                                 "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        before_history = self.history_path.read_bytes()
        verified = self.invoke_zip(self.zip.stem, "opSeq=APL,BRN,CHK,STS",
                                   "skipApproves=true")
        self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
        self.assertIn("Already satisfied: 3 [APL], 1 [BRN]", verified.stdout)
        self.assertEqual(self.history_path.read_bytes(), before_history)

    def test_goal_checked_can_continue_on_reassigned_branch(self):
        self.prepare_pending()
        moved = self.invoke_zip("op=BRN", f"featureBranch={self.TARGET}",
                                "skipApproves=true")
        self.assertEqual(moved.returncode, 0, moved.stderr + moved.stdout)
        preview = self.invoke_zip("goal=CHECKED", "planOnly=true")
        self.assertEqual(preview.returncode, 0, preview.stderr + preview.stdout)
        self.assertIn("PLAN CHECKED: CHK", preview.stdout)
        checked = self.invoke_zip("goal=CHECKED", "skipApproves=true")
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        self.assertIn("GOAL CHECKED: SUCCESS", checked.stdout)
        committed = self.invoke_zip("goal=COMMITTED", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stderr + committed.stdout)
        self.assertIn("GOAL COMMITTED: SUCCESS", committed.stdout)
        self.assertIn("Planned feature branch: feature/test-local-handoff",
                      self.history_path.read_text())

    def test_unrelated_unmerged_feature_branch_still_blocks_reassignment(self):
        self.prepare_pending()
        command("git", "switch", "-c", "feature/unrelated", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "unrelated work", cwd=self.root)
        command("git", "switch", "main", cwd=self.root)
        before = self.state_path.read_bytes()
        attempted = self.invoke_zip("op=BRN", f"featureBranch={self.TARGET}",
                                    "skipApproves=true")
        self.assertEqual(attempted.returncode, 2)
        self.assertIn("Unfinished local feature branch feature/unrelated", attempted.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

