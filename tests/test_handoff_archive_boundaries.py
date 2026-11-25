"""R3.3 structural and safety contracts for the handoff archive boundary."""

import hashlib
import json
import subprocess
import warnings
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apatch_lib.branch_patch import BranchPatchActions
from apatch_lib.mo_core.api import Abort
from apatch_lib.mo_handoff import api as handoff
from apatch_lib.mo_handoff import extraction, inspection, models


class HandoffArchiveBoundariesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.project = root / "service"
        self.project.mkdir()
        downloads = root / "downloads"
        downloads.mkdir()
        self.config = SimpleNamespace(downloads=downloads, max_bytes=100_000)
        self.filename = "service-PATCH-archive-contract.zip"
        self.payload = {
            "schema_version": 1,
            "repository": "service",
            "feature_branch": "feature/archive-contract",
            "patch_file": self.filename,
            "commit_message": "refactor: inspect ZIP\n\nPreserve safety checks.",
        }

    @staticmethod
    def member(name, data):
        info = zipfile.ZipInfo(name)
        info.create_system = 3
        info.external_attr = ((stat.S_IFREG | 0o644) << 16)
        return info, data

    def write_zip(self, *entries):
        path = self.config.downloads / self.filename
        with zipfile.ZipFile(path, "w") as target:
            target.writestr(*self.member(
                "service/.apatch/params.json", json.dumps(self.payload).encode()))
            for entry, data in entries:
                target.writestr(*self.member(entry, data))
        return path

    def load(self, *entries):
        path = self.write_zip(*(entries or (("service/new.txt", b"new\n"),)))
        return path, handoff.handoff_from_zip(self.config, self.project, self.filename)

    def test_public_port_reexports_canonical_archive_operations(self):
        self.assertIs(handoff.Archive, models.Archive)
        self.assertIs(handoff.inspect, inspection.inspect)
        self.assertIs(handoff.apply, extraction.apply)
        self.assertIs(handoff.handoff_from_zip, inspection.handoff_from_zip)
        self.assertIsInstance(handoff.ZipArchiveOperations(), handoff.ArchiveOperations)
        self.assertNotIsInstance(object(), handoff.ArchiveOperations)

    def test_boundaries_round_trip_without_workflow_or_journal_writes(self):
        path, selected = self.load()
        self.assertEqual(selected.patch_sha256, hashlib.sha256(path.read_bytes()).hexdigest())
        operations: handoff.ArchiveOperations = handoff.ZipArchiveOperations()
        inspected = operations.inspect(self.config, selected, self.project)
        self.assertEqual(inspected.changed, frozenset({"new.txt"}))
        self.assertEqual(inspected.embedded_handoff.patch_sha256, None)
        self.assertFalse((self.project / "new.txt").exists())
        operations.apply(self.config, selected, self.project, inspected)
        self.assertEqual((self.project / "new.txt").read_bytes(), b"new\n")
        self.assertFalse((self.project / ".apatch").exists())

    def test_zip_changes_after_inspection_are_rejected_before_source_write(self):
        path, selected = self.load()
        inspected = handoff.inspect(self.config, selected, self.project)
        with zipfile.ZipFile(path, "a") as target:
            target.writestr(*self.member("service/late.txt", b"late"))
        with self.assertRaisesRegex(Abort, "ZIP bytes changed after validation"):
            handoff.apply(self.config, selected, self.project, inspected)
        self.assertFalse((self.project / "new.txt").exists())
        self.assertFalse((self.project / "late.txt").exists())

    def test_unsafe_member_paths_are_rejected(self):
        for name in ("service/../escape.txt", "service/.git/config",
                     "another/file.txt", "service/.apatch/config.yaml"):
            with self.subTest(name=name):
                self.write_zip(("service/new.txt", b"ok"), (name, b"bad"))
                with self.assertRaises(Abort):
                    handoff.handoff_from_zip(self.config, self.project, self.filename)
                self.assertFalse((self.project / "new.txt").exists())

    def test_symlinked_destination_parent_is_rejected(self):
        external = self.project.parent / "external"
        external.mkdir()
        try:
            (self.project / "linked").symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable")
        self.write_zip(("service/linked/file.txt", b"untrusted"))
        with self.assertRaisesRegex(Abort, "Unsafe parent directory"):
            handoff.handoff_from_zip(self.config, self.project, self.filename)
        self.assertFalse((external / "file.txt").exists())

    def test_parent_symlink_swap_after_inspection_cannot_write_outside_repository(self):
        parent = self.project / "incoming"
        parent.mkdir()
        external = self.project.parent / "outside"
        external.mkdir()
        (external / "file.txt").write_bytes(b"external must survive\n")
        _, selected = self.load(("service/incoming/file.txt", b"ZIP data\n"))
        inspected = handoff.inspect(self.config, selected, self.project)
        original_inspect = extraction.inspect

        def swap_parent(*args, **kwargs):
            result = original_inspect(*args, **kwargs)
            parent.rename(self.project / "moved-incoming")
            parent.symlink_to(external, target_is_directory=True)
            return result

        with patch.object(extraction, "inspect", side_effect=swap_parent):
            with self.assertRaises(Abort):
                handoff.apply(self.config, selected, self.project, inspected)
        self.assertEqual((external / "file.txt").read_bytes(), b"external must survive\n")
        self.assertFalse((self.project / "moved-incoming" / "file.txt").exists())

    def test_symlink_swap_before_tracked_deletion_cannot_delete_external_file(self):
        def git(*args):
            subprocess.run(["git", *args], cwd=self.project, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        git("init")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "Archive Test")
        parent = self.project / "vault"
        parent.mkdir()
        (parent / "obsolete.txt").write_bytes(b"tracked original\n")
        git("add", "vault/obsolete.txt")
        git("commit", "-m", "Synthetic base")
        external = self.project.parent / "outside"
        external.mkdir()
        (external / "obsolete.txt").write_bytes(b"external must survive\n")
        self.payload["delete_paths"] = ["vault/obsolete.txt"]
        _, selected = self.load(("service/new.txt", b"new\n"))
        inspected = handoff.inspect(self.config, selected, self.project)
        original_replace = extraction.os.replace
        changed = False

        def swap_after_replacement(*args, **kwargs):
            nonlocal changed
            result = original_replace(*args, **kwargs)
            if not changed:
                changed = True
                parent.rename(self.project / "moved-vault")
                parent.symlink_to(external, target_is_directory=True)
            return result

        with patch.object(extraction.os, "replace", side_effect=swap_after_replacement):
            with self.assertRaises(Abort):
                handoff.apply(self.config, selected, self.project, inspected)
        self.assertTrue(changed)
        self.assertEqual((external / "obsolete.txt").read_bytes(), b"external must survive\n")
        self.assertEqual((self.project / "moved-vault" / "obsolete.txt").read_bytes(),
                         b"tracked original\n")

    def test_nested_extraction_preserves_existing_mode_and_zip_executable_bit(self):
        destination = self.project / "bin" / "existing.sh"
        destination.parent.mkdir()
        destination.write_bytes(b"old\n")
        destination.chmod(0o600)
        executable = zipfile.ZipInfo("service/bin/new.sh")
        executable.create_system = 3
        executable.external_attr = ((stat.S_IFREG | 0o755) << 16)
        path = self.config.downloads / self.filename
        with zipfile.ZipFile(path, "w") as target:
            target.writestr(*self.member(
                "service/.apatch/params.json", json.dumps(self.payload).encode()))
            target.writestr(*self.member("service/bin/existing.sh", b"updated\n"))
            target.writestr(executable, b"#!/bin/sh\nexit 0\n")
        selected = handoff.handoff_from_zip(self.config, self.project, self.filename)
        inspected = handoff.inspect(self.config, selected, self.project)
        handoff.apply(self.config, selected, self.project, inspected)
        self.assertEqual(destination.read_bytes(), b"updated\n")
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.project / "bin" / "new.sh").stat().st_mode), 0o755)

    def test_duplicate_source_entry_is_rejected(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self.write_zip(("service/new.txt", b"first"), ("service/new.txt", b"second"))
        with self.assertRaisesRegex(Abort, "Duplicate/conflicting path"):
            handoff.handoff_from_zip(self.config, self.project, self.filename)

    def test_oversized_archive_is_rejected(self):
        self.config.max_bytes = 10
        self.write_zip(("service/new.txt", b"oversized source"))
        with self.assertRaisesRegex(Abort, "maximum configured size|configured size"):
            handoff.handoff_from_zip(self.config, self.project, self.filename)

    def test_declared_tracked_deletion_is_applied_only_after_inspection(self):
        def git(*args):
            subprocess.run(["git", *args], cwd=self.project, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        git("init")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "Archive Test")
        obsolete = self.project / "obsolete.txt"
        obsolete.write_bytes(b"old\n")
        git("add", "obsolete.txt")
        git("commit", "-m", "Synthetic base")
        self.payload["delete_paths"] = ["obsolete.txt"]
        self.write_zip(("service/new.txt", b"new\n"))
        selected = handoff.handoff_from_zip(self.config, self.project, self.filename)
        before = handoff.inspect(self.config, selected, self.project)
        self.assertTrue(obsolete.is_file())
        self.assertEqual(before.changed, frozenset({"new.txt"}))
        handoff.apply(self.config, selected, self.project, before)
        self.assertFalse(obsolete.exists())
        self.assertEqual((self.project / "new.txt").read_bytes(), b"new\n")

    def test_untracked_deletion_is_rejected_without_changes(self):
        subprocess.run(["git", "init"], cwd=self.project, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        untracked = self.project / "untracked.txt"
        untracked.write_bytes(b"must survive\n")
        self.payload["delete_paths"] = ["untracked.txt"]
        self.write_zip(("service/new.txt", b"new\n"))
        with self.assertRaises(Abort):
            handoff.handoff_from_zip(self.config, self.project, self.filename)
        self.assertEqual(untracked.read_bytes(), b"must survive\n")
        self.assertFalse((self.project / "new.txt").exists())

    def test_injected_archive_port_is_used_by_branch_coordinator(self):
        selected = handoff.parse_handoff_payload(self.payload)
        inspected = handoff.Archive("a" * 64, frozenset({"new.txt"}))
        archive_ops = Mock(spec=handoff.ArchiveOperations)
        archive_ops.inspect.return_value = inspected
        workflow = SimpleNamespace(root=self.project, config=self.config,
                                   handoff=selected, source_handoff=selected)
        actions = BranchPatchActions(workflow, archive_ops=archive_ops)
        with patch("apatch_lib.branch_patch.assert_patch_order", return_value=True) as guard:
            self.assertTrue(actions.assert_patch_order(history=object()))
        archive_ops.inspect.assert_called_once_with(
            self.config, selected, self.project, before_apply=False)
        guard.assert_called_once()
