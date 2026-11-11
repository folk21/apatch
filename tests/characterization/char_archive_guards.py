"""Optional black-box baselines for ZIP trust boundaries and tracked deletions."""

import hashlib
import json
import stat
import zipfile

from tests._support import LocalGitFixture, command


class ArchiveGuardCharacterizationTests(LocalGitFixture):
    """A malformed archive must not mutate source files or commit history."""

    def _rewrite(self, *, metadata=None, entries=None) -> str:
        payload = {key: value for key, value in self.payload.items()
                   if key != "patch_sha256"}
        payload.update(metadata or {})
        with zipfile.ZipFile(self.zip, "w") as archive:
            for path, content in (entries if entries is not None else [
                ("existing.txt", "updated\n"), ("new.txt", "new\n"),
            ]):
                archive.writestr(f"{self.root.name}/{path}", content)
            archive.writestr(f"{self.root.name}/.apatch/params.json",
                             json.dumps(payload))
        return self.zip.stem

    def _assert_rejected_without_source_changes(self, selection: str) -> None:
        original_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout
        original_status = command("git", "status", "--porcelain", cwd=self.root).stdout
        result = self.invoke_zip("op=APL", "skipApproves=true", selection=selection)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout,
                         original_head)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         original_status)
        self.assertEqual((self.root / "existing.txt").read_bytes(), b"old\n")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.history_path.exists())

    def test_embedded_repository_mismatch_is_rejected(self) -> None:
        selection = self._rewrite(metadata={"repository": "another_service"})
        self._assert_rejected_without_source_changes(selection)

    def test_embedded_filename_mismatch_is_rejected(self) -> None:
        selection = self._rewrite(metadata={"patch_file": "example_service-PATCH-other.zip"})
        self._assert_rejected_without_source_changes(selection)

    def test_embedded_base_commit_mismatch_is_rejected(self) -> None:
        selection = self._rewrite(metadata={"base_commit": "f" * 40})
        self._assert_rejected_without_source_changes(selection)

    def test_embedded_hash_is_forbidden_and_does_not_authorize_apply(self) -> None:
        selection = self._rewrite(metadata={"patch_sha256": "f" * 64})
        self._assert_rejected_without_source_changes(selection)

    def test_duplicate_archive_members_are_rejected(self) -> None:
        selection = self.make_self_contained_zip()
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr(f"{self.root.name}/new.txt", "overwritten\n")
        self._assert_rejected_without_source_changes(selection)

    def test_symlink_archive_member_is_rejected(self) -> None:
        payload = {key: value for key, value in self.payload.items()
                   if key != "patch_sha256"}
        with zipfile.ZipFile(self.zip, "w") as archive:
            symlink = zipfile.ZipInfo(f"{self.root.name}/new.txt")
            symlink.create_system = 3
            symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(symlink, "../outside")
            archive.writestr(f"{self.root.name}/.apatch/params.json", json.dumps(payload))
        self._assert_rejected_without_source_changes(self.zip.stem)

    def test_declared_tracked_deletion_is_recorded_without_touching_unrelated_files(self) -> None:
        selection = self._rewrite(
            metadata={"delete_paths": ["existing.txt"]},
            entries=[("new.txt", "new\n")],
        )
        digest = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        result = self.invoke_zip("opSeq=APL,BRN,CHK,STS", "skipApproves=true",
                                 selection=selection)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "existing.txt").exists())
        self.assertEqual((self.root / "new.txt").read_bytes(), b"new\n")
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)
        self.assertEqual(hashlib.sha256(self.zip.read_bytes()).hexdigest(), digest)
        self.assertIn("existing.txt", command("git", "status", "--porcelain", cwd=self.root).stdout)
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertEqual(record["archive_sha256"], digest)

    def test_deletion_cannot_target_runtime_metadata(self) -> None:
        selection = self._rewrite(
            metadata={"delete_paths": [".apatch/config.yaml"]},
            entries=[("new.txt", "new\n")],
        )
        original = self.project_config.read_bytes()
        self._assert_rejected_without_source_changes(selection)
        self.assertEqual(self.project_config.read_bytes(), original)


if __name__ == "__main__":
    import unittest
    unittest.main()
