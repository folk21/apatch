"""RE-05 retention, export, and interrupted-cleanup recovery contracts."""

import hashlib
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from apatch_lib.model import Abort
from apatch_lib.review_retention import (_retention_locked, export_review_summary,
                                         prune_review_artifacts, review_storage_lock)


class ReviewRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".apatch").mkdir()
        self.reviews = self.root / ".apatch" / "reviews"
        self.reviews.mkdir(mode=0o700)

    def run_dir(self, number, *, status="COMPLETED", provider=False):
        name = "review-" + f"{number:024x}"
        directory = self.reviews / name
        directory.mkdir(mode=0o700)
        providers = []
        if provider:
            stdout = b"SECRET_RAW_TOKEN=keep-local"
            stderr = b"secret stderr"
            for suffix, payload in (("stdout", stdout), ("stderr", stderr)):
                self.member(directory, "scan." + suffix, payload)
            providers = [{"id": "scan", "kind": "script", "exit_code": 0,
                          "timed_out": False, "truncated": False,
                          **{suffix + "_file": "scan." + suffix for suffix in ("stdout", "stderr")},
                          **{suffix + "_bytes": len(payload) for suffix, payload in (("stdout", stdout), ("stderr", stderr))},
                          **{suffix + "_sha256": hashlib.sha256(payload).hexdigest()
                             for suffix, payload in (("stdout", stdout), ("stderr", stderr))}}]
        manifest = {"schema_version": 1, "review_id": name, "status": status,
                    "snapshot": ["feature/example", "a" * 40, "b" * 64, "", "c" * 64],
                    "providers": providers}
        self.member(directory, "manifest.json", (json.dumps(manifest) + "\n").encode())
        return directory

    @staticmethod
    def member(directory, name, payload):
        file = directory / name
        file.write_bytes(payload)
        file.chmod(0o600)
        return file

    def test_defaults_preview_without_deleting(self):
        old = self.run_dir(1)
        os.utime(old, (time.time() - 90 * 86400,) * 2)
        result = prune_review_artifacts(self.root)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.removed, (old.name,))
        self.assertTrue(old.exists())
        self.assertEqual(stat.S_IMODE((self.reviews / ".retention.lock").stat().st_mode), 0o600)

    def test_count_age_and_size_rules_keep_recent_results(self):
        oldest = self.run_dir(1)
        middle = self.run_dir(2)
        newest = self.run_dir(3)
        for index, directory in enumerate((oldest, middle, newest)):
            os.utime(directory, (time.time() - (3 - index) * 86400,) * 2)
        result = prune_review_artifacts(self.root, max_runs=1, max_age_days=365,
                                        dry_run=False)
        self.assertEqual(result.removed, (oldest.name, middle.name))
        self.assertFalse(oldest.exists())
        self.assertTrue(newest.exists())
        byte_limit = 1048576
        big = self.run_dir(4)
        self.member(big, "unexpected", b"x")
        self.assertIn(big.name, prune_review_artifacts(
            self.root, max_runs=1, max_bytes=byte_limit).protected)

    def test_byte_quota_evicts_oldest_verified_history(self):
        old = self.run_dir(1, provider=True)
        newer = self.run_dir(2, provider=True)
        for days, directory in ((7, old), (2, newer)):
            os.utime(directory, (time.time() - days * 86400,) * 2)
        preview = prune_review_artifacts(self.root, max_runs=100,
                                         max_bytes=1048576, max_age_days=365)
        self.assertEqual(preview.removed, ())
        # Byte pressure is exercised by reserving capacity during maintenance.
        from apatch_lib.review_retention import _retention_locked
        with review_storage_lock(self.root) as fd:
            preview = _retention_locked(fd, max_runs=100, max_bytes=1048576,
                                        max_age_days=365, dry_run=True,
                                        reserve_bytes=1048576)
        self.assertEqual(preview.removed, (old.name, newer.name))

    def test_automatic_reservation_rejects_protected_history_without_pruning(self):
        old = self.run_dir(1)
        incomplete = self.run_dir(2, status="STARTED")
        os.utime(old, (time.time() - 90 * 86400,) * 2)
        old_contents = (old / "manifest.json").read_bytes()
        with review_storage_lock(self.root) as fd:
            with self.assertRaisesRegex(Abort, "REVIEW_RETENTION_QUOTA"):
                _retention_locked(fd, max_runs=1, max_bytes=1048576,
                                  max_age_days=30, dry_run=False, reserve_runs=1)
        self.assertEqual((old / "manifest.json").read_bytes(), old_contents)
        self.assertTrue(incomplete.exists())
        self.assertEqual(sorted(path.name for path in self.reviews.iterdir()),
                         sorted([".retention.lock", incomplete.name, old.name]))

    def test_automatic_reservation_beyond_quota_preserves_verified_history(self):
        old = self.run_dir(1)
        os.utime(old, (time.time() - 90 * 86400,) * 2)
        old_contents = (old / "manifest.json").read_bytes()
        with review_storage_lock(self.root) as fd:
            with self.assertRaisesRegex(Abort, "REVIEW_RETENTION_QUOTA"):
                _retention_locked(fd, max_runs=1, max_bytes=1048576,
                                  max_age_days=30, dry_run=False,
                                  reserve_runs=1, reserve_bytes=1048577)
        self.assertEqual((old / "manifest.json").read_bytes(), old_contents)

    def test_feasible_automatic_reservation_prunes_only_verified_history(self):
        old = self.run_dir(1)
        with review_storage_lock(self.root) as fd:
            result = _retention_locked(fd, max_runs=1, max_bytes=1048576,
                                       max_age_days=365, dry_run=False, reserve_runs=1)
        self.assertEqual(result.removed, (old.name,))
        self.assertFalse(old.exists())

    def test_explicit_pruning_remains_independent_of_reservation_admission(self):
        old = self.run_dir(1)
        incomplete = self.run_dir(2, status="STARTED")
        os.utime(old, (time.time() - 90 * 86400,) * 2)
        result = prune_review_artifacts(self.root, max_runs=1, max_age_days=30,
                                        dry_run=False)
        self.assertEqual(result.removed, (old.name,))
        self.assertIn(incomplete.name, result.protected)
        self.assertFalse(old.exists())
        self.assertTrue(incomplete.exists())

    def test_unknown_and_incomplete_directories_never_pruned(self):
        incomplete = self.run_dir(1, status="STARTED")
        corrupted = self.run_dir(2)
        (corrupted / "manifest.json").write_text("broken", encoding="utf-8")
        custom = self.reviews / "my-personal-files"
        custom.mkdir()
        symlink = self.reviews / ("review-" + "f" * 24)
        symlink.symlink_to(custom, target_is_directory=True)
        hardlinked = self.run_dir(3)
        os.link(hardlinked / "manifest.json", self.root / "external")
        result = prune_review_artifacts(self.root, max_runs=1, dry_run=False)
        self.assertEqual(result.removed, ())
        for item in (incomplete, corrupted, custom, symlink, hardlinked):
            self.assertTrue(item.exists() or item.is_symlink())
            self.assertIn(item.name, result.protected)

    def test_unknown_files_and_symlinked_members_are_not_deleted(self):
        directory = self.run_dir(1)
        self.member(directory, "personal.txt", b"keep")
        result = prune_review_artifacts(self.root, max_runs=1, max_age_days=1,
                                        dry_run=False)
        self.assertEqual(result.removed, ())
        self.assertTrue((directory / "personal.txt").exists())
        (directory / "personal.txt").unlink()
        (directory / "manifest.json").unlink()
        (directory / "manifest.json").symlink_to(self.root / "outside")
        self.assertIn(directory.name, prune_review_artifacts(self.root).protected)

    def test_export_requires_consent_and_does_not_include_secrets_or_paths(self):
        directory = self.run_dir(1, provider=True)
        with self.assertRaisesRegex(Abort, "REVIEW_EXPORT_CONSENT"):
            export_review_summary(self.root, directory.name)
        payload = export_review_summary(self.root, directory.name, consent=True)
        self.assertFalse((self.reviews / ".retention.lock").exists())
        summary = json.loads(payload)
        self.assertEqual(summary["status"], "COMPLETED")
        self.assertEqual(summary["providers"][0]["id"], "scan")
        for value in (b"SECRET", b"secret stderr", b"feature/example", b"scan.stdout"):
            self.assertNotIn(value, payload)
        (directory / "scan.stdout").write_bytes(b"modified")
        with self.assertRaisesRegex(Abort, "REVIEW_EXPORT_UNKNOWN"):
            export_review_summary(self.root, directory.name, consent=True)

    def test_failed_export_is_metadata_only_and_started_is_blocked(self):
        failed = self.run_dir(1, status="FAILED", provider=True)
        self.assertEqual(json.loads(export_review_summary(
            self.root, failed.name, consent=True))["status"], "FAILED")
        started = self.run_dir(2, status="STARTED")
        with self.assertRaisesRegex(Abort, "REVIEW_EXPORT_UNKNOWN"):
            export_review_summary(self.root, started.name, consent=True)

    def test_interruption_during_unlink_recovers_from_prune_journal(self):
        directory = self.run_dir(1, provider=True)
        os.utime(directory, (time.time() - 90 * 86400,) * 2)
        original = os.unlink
        encountered = [False]

        def interrupted(name, *, dir_fd=None):
            if name == "scan.stdout" and not encountered[0]:
                encountered[0] = True
                raise OSError("simulated interrupted deletion")
            return original(name, dir_fd=dir_fd)

        with mock.patch("apatch_lib.review_retention.os.unlink", side_effect=interrupted):
            with self.assertRaisesRegex(Abort, "REVIEW_RETENTION_UNSAFE"):
                prune_review_artifacts(self.root, dry_run=False)
        pending = self.reviews / directory.name.replace("review-", "pruning-")
        self.assertTrue(pending.exists())
        self.assertTrue((pending / ".prune-intent.json").exists())
        prune_review_artifacts(self.root, dry_run=False)
        self.assertFalse(pending.exists())
        self.assertFalse(directory.exists())

    def test_modified_pending_member_preserved_for_manual_recovery(self):
        directory = self.run_dir(1)
        os.utime(directory, (time.time() - 90 * 86400,) * 2)
        with mock.patch("apatch_lib.review_retention.os.unlink", side_effect=OSError("stop")):
            with self.assertRaises(Abort):
                prune_review_artifacts(self.root, dry_run=False)
        pending = self.reviews / directory.name.replace("review-", "pruning-")
        (pending / "manifest.json").write_text("tampered")
        result = prune_review_artifacts(self.root, dry_run=False)
        self.assertIn(pending.name, result.protected)
        self.assertTrue((pending / "manifest.json").exists())

    def test_lock_serializes_concurrent_review_storage_users(self):
        acquired = threading.Event()
        released = threading.Event()

        def contender():
            with review_storage_lock(self.root):
                acquired.set()
                released.wait(timeout=2)

        with review_storage_lock(self.root):
            thread = threading.Thread(target=contender, daemon=True)
            thread.start()
            self.assertFalse(acquired.wait(timeout=0.1))
        self.assertTrue(acquired.wait(timeout=2))
        released.set()
        thread.join(timeout=2)

    def test_policy_validation_refuses_boolean_and_unbounded_input(self):
        for values in ({"max_runs": True}, {"max_runs": 0},
                       {"max_bytes": 50}, {"max_age_days": 0}):
            with self.subTest(values=values), self.assertRaisesRegex(Abort, "REVIEW_RETENTION_POLICY"):
                prune_review_artifacts(self.root, **values)


if __name__ == "__main__":
    unittest.main()
