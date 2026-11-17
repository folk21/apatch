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

from apatch_lib import patch as legacy_patch
from apatch_lib.branch_patch import BranchPatchActions
from apatch_lib.core.api import Abort
from apatch_lib.handoff import api as handoff


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

    def test_public_port_is_structural_and_legacy_objects_preserve_identity(self):
        self.assertIs(legacy_patch.Archive, handoff.Archive)
        self.assertIs(legacy_patch.inspect, handoff.inspect)
        self.assertIs(legacy_patch.apply, handoff.apply)
        self.assertIs(legacy_patch.handoff_from_zip, handoff.handoff_from_zip)
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
