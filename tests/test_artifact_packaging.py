"""Verified producer ZIP packaging with isolated local Git fixtures."""

import json
import shutil
import stat
import subprocess
import sys
from unittest.mock import patch
import zipfile

import apatch_lib.artifact_packaging as packaging
from apatch_lib.artifact_packaging import pack_source
from apatch_lib.model import Abort, load_config, load_project_config
from apatch_lib.patch import handoff_from_zip, inspect
from tests._support import TOOL, LocalGitFixture, command


class ArtifactPackagingTests(LocalGitFixture):
    def setUp(self):
        super().setUp()
        (self.root / "new.txt").write_text("generated\n")
        self.destination = self.base / "downloads" / "example_service-PATCH-packaging.zip"

    def build(self, *, included=("new.txt",), deleted=(), prepare=False,
              destination=None):
        return pack_source(
            self.root, self.bin, destination or self.destination,
            branch="feature/producer-packaging", message="feat: package checked source",
            included=tuple(included), deleted=tuple(deleted), prepare=prepare)

    def test_packaging_embeds_exact_source_and_valid_handoff(self):
        result = self.build()
        self.assertEqual(result.files, ("new.txt",))
        self.assertEqual(result.source.changed_paths, ("new.txt",))
        self.assertEqual(result.source.check_commands_run, 1)
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(archive.namelist(), [
                "example_service/new.txt", "example_service/.apatch/params.json"])
            self.assertEqual(archive.read("example_service/new.txt"), b"generated\n")
            payload = json.loads(archive.read("example_service/.apatch/params.json"))
            self.assertEqual(payload["feature_branch"], "feature/producer-packaging")
            self.assertEqual(payload["base_commit"], None)
            self.assertEqual(archive.testzip(), None)
        config = load_project_config(self.root, load_config(self.bin))
        handoff = handoff_from_zip(config, self.root, self.destination.name)
        self.assertEqual(inspect(config, handoff, self.root).changed, frozenset({"new.txt"}))
        self.assertEqual(result.to_dict()["status"], "passed")

    def test_failed_check_never_produces_zip(self):
        (self.root / "run_checks.sh").write_text("#!/bin/sh\nexit 5\n")
        with self.assertRaisesRegex(Abort, "CHECK 1/1 failed"):
            self.build()
        self.assertFalse(self.destination.exists())

    def test_changes_between_preflight_and_packaging_are_blocked(self):
        original = packaging.preflight

        def change_source(*args, **kwargs):
            evidence = original(*args, **kwargs)
            (self.root / "new.txt").write_text("unverified\n")
            return evidence

        with patch("apatch_lib.artifact_packaging.preflight", side_effect=change_source):
            with self.assertRaisesRegex(Abort, "Source changed after preflight"):
                self.build()
        self.assertFalse(self.destination.exists())

    def test_changes_while_reading_source_discard_temporary_zip(self):
        original = packaging._read_source_file

        def change_after_read(root, name, limit):
            result = original(root, name, limit)
            (self.root / name).write_text("new content after read\n")
            return result

        with patch("apatch_lib.artifact_packaging._read_source_file",
                   side_effect=change_after_read):
            with self.assertRaisesRegex(Abort, "Source changed during ZIP creation"):
                self.build()
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.glob(".apatch-pack-*.tmp")), [])

    def test_archive_member_must_match_verified_source_bytes(self):
        with patch("apatch_lib.artifact_packaging._read_source_file",
                   return_value=(b"different bytes\n", 0o644)):
            with self.assertRaisesRegex(Abort, "Packaged source bytes or mode changed"):
                self.build()
        self.assertFalse(self.destination.exists())

    def test_undeclared_changes_cannot_be_omitted(self):
        (self.root / "existing.txt").write_text("edited\n")
        with self.assertRaisesRegex(Abort, "outside the packaging manifest"):
            self.build()
        self.assertFalse(self.destination.exists())

    def test_existing_output_refused_without_overwriting(self):
        self.destination.write_bytes(b"keep these bytes")
        with self.assertRaisesRegex(Abort, "already exists"):
            self.build()
        self.assertEqual(self.destination.read_bytes(), b"keep these bytes")

    def test_output_symlink_refused_without_touching_target(self):
        private = self.base / "keep.txt"
        private.write_text("keep\n")
        self.destination.symlink_to(private)
        with self.assertRaisesRegex(Abort, "must not be a symlink"):
            self.build()
        self.assertEqual(private.read_text(), "keep\n")

    def test_output_inside_source_checkout_refused(self):
        destination = self.root / self.destination.name
        with self.assertRaisesRegex(Abort, "outside the source Git repository"):
            self.build(destination=destination)
        self.assertFalse(destination.exists())

    def test_untracked_symlink_is_never_packaged(self):
        external = self.base / "private.txt"
        external.write_text("private\n")
        (self.root / "new.txt").unlink()
        (self.root / "new.txt").symlink_to(external)
        with self.assertRaisesRegex(Abort, "regular non-symlink file"):
            self.build()
        self.assertFalse(self.destination.exists())

    def test_protected_paths_are_rejected_before_checks(self):
        with self.assertRaisesRegex(Abort, "protected apatch path"):
            self.build(included=(".apatch/config.yaml",))
        self.assertFalse(self.destination.exists())

    def test_missing_preparation_configuration_blocks_archive(self):
        with self.assertRaisesRegex(Abort, "requires project format_commands"):
            self.build(prepare=True)
        self.assertFalse(self.destination.exists())

    def test_explicit_deletion_is_embedded_in_handoff(self):
        (self.root / "existing.txt").unlink()
        result = self.build(deleted=("existing.txt",))
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(archive.namelist(), [
                "example_service/new.txt", "example_service/.apatch/params.json"])
            payload = json.loads(archive.read("example_service/.apatch/params.json"))
            self.assertEqual(payload["delete_paths"], ["existing.txt"])
        self.assertEqual(result.deleted_paths, ("existing.txt",))

    def test_executable_mode_is_preserved(self):
        (self.root / "new.txt").chmod(0o755)
        self.build()
        with zipfile.ZipFile(self.destination) as archive:
            info = archive.getinfo("example_service/new.txt")
        self.assertEqual((info.external_attr >> 16) & 0o777, 0o755)
        self.assertEqual((info.external_attr >> 16) & 0o170000,
                         stat.S_IFREG)

    def test_formatter_runs_before_build_and_is_verified(self):
        script = self.root / "format.sh"
        script.write_text("#!/bin/sh\nset -eu\nprintf 'formatted\\n' > new.txt\n")
        script.chmod(0o755)
        self.project_config.write_text(self.project_config.read_text()
                                       + 'format_commands:\n  - ["./format.sh"]\n')
        command("git", "add", ".apatch/config.yaml", "format.sh", cwd=self.root)
        command("git", "commit", "-m", "add project formatter", cwd=self.root)
        result = self.build(prepare=True)
        self.assertTrue(result.source.prepared)
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(archive.read("example_service/new.txt"), b"formatted\n")

    def test_json_cli_returns_single_result_for_both_outcomes(self):
        shutil.copy(TOOL / "apatch_pack.py", self.bin / "apatch_pack.py")
        command_line = [sys.executable, str(self.bin / "apatch_pack.py"),
                        "--project", str(self.root), "--output", str(self.destination),
                        "--branch", "feature/producer-packaging",
                        "--message", "feat: package checked source", "--include", "new.txt",
                        "--json"]
        completed = subprocess.run(command_line, cwd=self.root, capture_output=True,
                                   text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "passed")
        repeated = subprocess.run(command_line, cwd=self.root, capture_output=True,
                                  text=True, timeout=20)
        self.assertEqual(repeated.returncode, 1)
        self.assertEqual(json.loads(repeated.stdout)["status"], "failed")
        self.assertIn("already exists", repeated.stderr)


if __name__ == "__main__":
    import unittest
    unittest.main()
