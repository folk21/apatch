"""Cross-boundary producer, local publication, and review admission baselines."""

import hashlib
import json
import shutil
import sys
import zipfile

from tests._support import LocalGitFixture, TOOL, command, run_bounded


class ProducerReviewCharacterizationTests(LocalGitFixture):
    """Exercise public tools against a disposable repository and bare remote."""

    def _install_tool(self, name: str) -> None:
        shutil.copy(TOOL / name, self.bin / name)

    def _producer(self, name: str, *args: str):
        self._install_tool(name)
        return run_bounded([sys.executable, str(self.bin / name),
                            "--project", str(self.root), *args], cwd=self.root)

    def test_discover_json_does_not_publish_or_modify_source(self) -> None:
        (self.root / "new.txt").write_text("new\n")
        before = command("git", "status", "--porcelain", cwd=self.root).stdout

        result = self._producer("apatch_pack.py", "--discover", "--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "candidates")
        self.assertEqual(data["include"], ["new.txt"])
        self.assertEqual(data["untracked"], ["new.txt"])
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         before)
        self.assertFalse(any((self.base / "downloads").glob("*packaged*.zip")))

    def test_preflight_json_binds_changed_bytes_to_exact_head(self) -> None:
        (self.root / "new.txt").write_text("new\n")
        before = command("git", "status", "--porcelain", cwd=self.root).stdout

        result = self._producer("apatch_preflight.py", "--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "passed")
        self.assertEqual(data["head"], self.head)
        self.assertEqual(data["changed_paths"], ["new.txt"])
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         before)

    def test_packaged_zip_is_consumed_without_metadata_repackaging(self) -> None:
        (self.root / "existing.txt").write_text("worker-produced\n")
        (self.root / "new.txt").write_text("worker-added\n")
        archive = self.base / "downloads" / "example_service-PATCH-packaged.zip"
        message = "test: preserve producer verification\n\n- Package checked source."

        result = self._producer(
            "apatch_pack.py", "--json", "--output", str(archive),
            "--branch", "feature/producer-consumer", "--message", message,
            "--base-commit", self.head,
            "--include", "existing.txt", "--include", "new.txt",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "passed")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(data["zip_sha256"], digest)
        with zipfile.ZipFile(archive) as bundle:
            embedded = json.loads(bundle.read("example_service/.apatch/params.json"))
            self.assertEqual(embedded["feature_branch"], "feature/producer-consumer")
            self.assertEqual(embedded["patch_file"], archive.name)
            self.assertNotIn("patch_sha256", embedded)
            self.assertEqual(bundle.read("example_service/new.txt"), b"worker-added\n")
        command("git", "restore", "--", "existing.txt", cwd=self.root)
        (self.root / "new.txt").unlink()
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         "")

        consumed = self.invoke_zip("opSeq=APL,BRN,CHK,STS", "skipApproves=true",
                                   selection=archive.stem)

        self.assertEqual(consumed.returncode, 0, consumed.stdout + consumed.stderr)
        self.assertEqual((self.root / "existing.txt").read_bytes(), b"worker-produced\n")
        self.assertEqual((self.root / "new.txt").read_bytes(), b"worker-added\n")
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), digest)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)

    def test_producer_refuses_to_hide_unselected_changes(self) -> None:
        (self.root / "new.txt").write_text("new\n")
        (self.root / "existing.txt").write_text("unselected edit\n")
        archive = self.base / "downloads" / "example_service-PATCH-packaged.zip"
        result = self._producer(
            "apatch_pack.py", "--json", "--output", str(archive),
            "--branch", "feature/producer-consumer", "--message", "test: reject hidden scope",
            "--include", "new.txt",
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")
        self.assertFalse(archive.exists())
        self.assertEqual((self.root / "existing.txt").read_text(), "unselected edit\n")

    def test_unconfigured_review_does_not_change_checked_source_or_publish(self) -> None:
        selection = self.make_self_contained_zip()
        ready = self.invoke_zip("opSeq=APL,BRN,CHK", "skipApproves=true",
                                selection=selection)
        self.assertEqual(ready.returncode, 0, ready.stdout + ready.stderr)
        previous_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout
        previous_tree = command("git", "status", "--porcelain", cwd=self.root).stdout

        result = self.invoke_zip("opSeq=REV,CMT,PSH", "skipApproves=true")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout,
                         previous_head)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         previous_tree)
        self.assertFalse(command("git", "ls-remote", "--heads", "origin",
                                 "refs/heads/feature/test-local-handoff",
                                 cwd=self.root).stdout.strip())
        self.assertFalse((self.root / ".apatch" / "reviews").exists())

    def test_publication_cannot_skip_commit_after_local_verification(self) -> None:
        selection = self.make_self_contained_zip()
        ready = self.invoke_zip("--strict", "opSeq=APL,BRN,CHK", "skipApproves=true",
                                selection=selection)
        self.assertEqual(ready.returncode, 0, ready.stdout + ready.stderr)

        publish = self.invoke_zip("--strict", "opSeq=PSH,PR,MRG", "skipApproves=true")

        self.assertNotEqual(publish.returncode, 0, publish.stdout + publish.stderr)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)
        self.assertFalse(command("git", "ls-remote", "--heads", "origin",
                                 "refs/heads/feature/test-local-handoff",
                                 cwd=self.root).stdout.strip())


if __name__ == "__main__":
    import unittest
    unittest.main()
