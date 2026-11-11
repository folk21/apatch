"""Optional public compatibility tests for explicit ZIP destination selection."""

import hashlib
import json

from tests._support import LocalGitFixture, command


class DestinationSelectionCharacterizationTests(LocalGitFixture):
    """Preserve ZIP provenance when the developer selects a different feature branch."""

    TARGET = "feature/characterization-selected-destination"

    def test_new_destination_is_created_without_rewriting_embedded_metadata(self) -> None:
        stem = self.make_self_contained_zip()
        original_digest = hashlib.sha256(self.zip.read_bytes()).hexdigest()

        result = self.invoke_zip(stem, f"featureBranch={self.TARGET}",
                                 "opSeq=APL,BRN,CHK,STS", "skipApproves=true")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.TARGET)
        self.assertEqual(hashlib.sha256(self.zip.read_bytes()).hexdigest(), original_digest)
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["source_branch"], self.payload["feature_branch"])
        self.assertEqual(record["branch"], self.TARGET)
        self.assertEqual(record["archive_sha256"], original_digest)
        self.assertEqual(json.loads((self.root / ".apatch" / "params.json").read_text())[
                             "feature_branch"], self.payload["feature_branch"])

    def test_alternate_embedded_branch_can_follow_verified_pending_work(self) -> None:
        self.make_self_contained_zip()
        first = self.invoke_zip("opSeq=APL,BRN", "skipApproves=true",
                                selection=self.zip.stem)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.make_followup_zip(override={"feature_branch": "feature/retired-name"})
        original_digest = hashlib.sha256(second.read_bytes()).hexdigest()

        result = self.invoke_zip(second.stem, "followup=true",
                                 f"featureBranch={self.payload['feature_branch']}",
                                 "opSeq=APL,CHK,STS", "skipApproves=true")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(hashlib.sha256(second.read_bytes()).hexdigest(), original_digest)
        state = json.loads(self.state_path.read_text())
        record = next(item for item in state["workflows"].values()
                      if item["patch_file"] == second.name)
        self.assertEqual(record["source_branch"], "feature/retired-name")
        self.assertEqual(record["branch"], self.payload["feature_branch"])
        self.assertEqual(record["archive_sha256"], original_digest)
        self.assertIn("Planned feature branch: feature/retired-name",
                      self.history_path.read_text())

    def test_mismatched_destination_does_not_consume_or_modify_followup_zip(self) -> None:
        self.make_self_contained_zip()
        first = self.invoke_zip("opSeq=APL,BRN", "skipApproves=true",
                                selection=self.zip.stem)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.make_followup_zip(override={"feature_branch": "feature/old-intent"})
        before_digest = hashlib.sha256(second.read_bytes()).hexdigest()
        before_history = self.history_path.read_bytes()

        blocked = self.invoke_zip(second.stem, "followup=true",
                                  f"featureBranch={self.TARGET}", "op=APL",
                                  "skipApproves=true")

        self.assertNotEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)
        self.assertEqual(hashlib.sha256(second.read_bytes()).hexdigest(), before_digest)
        self.assertEqual(self.history_path.read_bytes(), before_history)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")
        self.assertFalse((self.root / "second.txt").exists())

    def test_force_mode_does_not_authorize_upfront_destination_override(self) -> None:
        stem = self.make_self_contained_zip()
        blocked = self.invoke_zip(stem, "--force", f"featureBranch={self.TARGET}",
                                  "op=APL", "skipApproves=true")
        self.assertNotEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)
        self.assertEqual((self.root / "existing.txt").read_text(), "old\n")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.history_path.exists())


if __name__ == "__main__":
    import unittest
    unittest.main()
