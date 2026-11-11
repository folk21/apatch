"""Characterize cross-process ZIP lifecycle, continuation, and recovery guards."""

import hashlib
import json
import zipfile

from tests._support import LocalGitFixture, command


class RecoveryCharacterizationTests(LocalGitFixture):
    """Verify live Git and persisted evidence remain authoritative on retries."""

    def _apply_and_branch(self) -> str:
        selection = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN", "skipApproves=true",
                                 selection=selection)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return selection

    def test_explicit_zip_restart_after_branch_creation_does_not_replay_bytes(self) -> None:
        selection = self._apply_and_branch()
        history = self.history_path.read_bytes()
        digest = hashlib.sha256(self.zip.read_bytes()).hexdigest()

        restarted = self.invoke_zip("opSeq=APL,BRN,CHK,STS", "skipApproves=true",
                                    selection=selection)

        self.assertEqual(restarted.returncode, 0, restarted.stdout + restarted.stderr)
        self.assertEqual(self.history_path.read_bytes(), history)
        self.assertEqual(hashlib.sha256(self.zip.read_bytes()).hexdigest(), digest)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertEqual(record["phase"], "verified")

    def test_second_zip_requires_explicit_followup_on_pending_branch(self) -> None:
        self._apply_and_branch()
        followup = self.make_followup_zip()
        prior_history = self.history_path.read_bytes()
        prior_bytes = (self.root / "existing.txt").read_bytes()

        denied = self.invoke_zip("op=APL", "skipApproves=true",
                                 selection=followup.stem)

        self.assertNotEqual(denied.returncode, 0, denied.stdout + denied.stderr)
        self.assertEqual(self.history_path.read_bytes(), prior_history)
        self.assertEqual((self.root / "existing.txt").read_bytes(), prior_bytes)
        self.assertFalse((self.root / "second.txt").exists())
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)

    def test_explicit_followup_preserves_both_patch_histories(self) -> None:
        self._apply_and_branch()
        followup = self.make_followup_zip()
        second_digest = hashlib.sha256(followup.read_bytes()).hexdigest()

        result = self.invoke_zip("opSeq=APL,CHK,STS", "followup=true",
                                 "skipApproves=true", selection=followup.stem)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / "existing.txt").read_text(), "second revision\n")
        self.assertEqual((self.root / "second.txt").read_text(), "second patch\n")
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(len(state["workflows"]), 2)
        self.assertIn(followup.name, self.history_path.read_text())
        self.assertTrue(any(record.get("archive_sha256") == second_digest
                            for record in state["workflows"].values()))

    def test_corrupt_persisted_state_does_not_get_overwritten_by_status(self) -> None:
        self._apply_and_branch()
        self.state_path.write_text('{"truncated":', encoding="utf-8")
        broken_bytes = self.state_path.read_bytes()
        original_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout

        result = self.invoke_zip("op=STS", "skipApproves=true")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state_path.read_bytes(), broken_bytes)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout,
                         original_head)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")

    def test_lost_cache_cannot_authorize_duplicate_apl(self) -> None:
        selection = self._apply_and_branch()
        cache = self.root / ".apatch" / "params.json"
        cache.unlink()
        history = self.history_path.read_bytes()

        denied = self.invoke_zip("op=APL", "skipApproves=true", selection=selection)

        self.assertNotEqual(denied.returncode, 0, denied.stdout + denied.stderr)
        self.assertEqual(self.history_path.read_bytes(), history)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")

    def test_unmerged_local_feature_work_blocks_new_branch_with_approvals_skipped(self) -> None:
        command("git", "switch", "-c", "feature/outstanding", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "Unmerged change", cwd=self.root)
        command("git", "switch", "main", cwd=self.root)
        selection = self.make_self_contained_zip()

        blocked = self.invoke_zip("opSeq=APL,BRN,CHK", "skipApproves=true",
                                  selection=selection)

        self.assertNotEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "main")
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)
        self.assertFalse((self.root / "new.txt").is_symlink())
        self.assertFalse(command("git", "branch", "--list", self.payload["feature_branch"],
                                 cwd=self.root).stdout.strip())


if __name__ == "__main__":
    import unittest
    unittest.main()
