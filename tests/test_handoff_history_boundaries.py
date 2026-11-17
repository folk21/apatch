"""Contracts, persistence, and compatibility for handoff-owned patch history."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

from apatch_lib.branch_patch import BranchPatchActions
from apatch_lib.core.api import Abort
from apatch_lib.created_patches import (
    MAX_REGISTRY_BYTES as LEGACY_MAX_REGISTRY_BYTES,
    assert_patch_order as legacy_assert_order,
    persist_registry as legacy_persist_registry,
)
from apatch_lib.patch_history import (
    AppliedPatchHistory as LegacyAppliedPatchHistory,
    HistoryEntry as LegacyHistoryEntry,
    locked_history as legacy_locked_history,
)
from apatch_lib.handoff.api import PatchLedgerOperations, ProjectPatchLedger
from apatch_lib.handoff.history.api import AppliedHistory
from apatch_lib.handoff.history.journal import AppliedPatchHistory, locked_history, parse_history
from apatch_lib.handoff.history.models import HistoryEntry
from apatch_lib.handoff.history.registry import (
    MAX_REGISTRY_BYTES, assert_patch_order, parse_registry, persist_registry,
    read_registry, registry_path,
)


FIRST = "apatch-PATCH-2026-11-17-14-01-first.zip"
SECOND = "apatch-PATCH-2026-11-17-14-02-second.zip"


class HandoffHistoryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="apatch-ledger-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "example"
        (self.root / ".apatch").mkdir(parents=True)
        self.path = self.root / ".apatch" / "applied_patches.txt"

    def test_cold_import_orders_do_not_cycle_through_shared_locking(self):
        # Fresh interpreters expose import cycles hidden by unittest module caching.
        source_root = Path(__file__).resolve().parents[1]
        import_orders = (
            "from apatch_lib.patch_history import locked_history; "
            "from apatch_lib.handoff.api import ProjectPatchLedger",
            "from apatch_lib.created_patches import persist_registry; "
            "from apatch_lib.handoff.history.journal import locked_history",
            "from apatch_lib.storage.locking import Abort; "
            "from apatch_lib.core.errors import Abort as CoreAbort; "
            "assert Abort is CoreAbort",
        )
        for source in import_orders:
            with self.subTest(source=source):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", source], cwd=source_root,
                    capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_protocol_and_legacy_imports_preserve_identity(self):
        ledger = ProjectPatchLedger()
        self.assertIsInstance(ledger, PatchLedgerOperations)
        self.assertIs(LegacyAppliedPatchHistory, AppliedPatchHistory)
        self.assertIs(LegacyHistoryEntry, HistoryEntry)
        self.assertIs(legacy_locked_history, locked_history)
        self.assertIs(legacy_persist_registry, persist_registry)
        self.assertIs(legacy_assert_order, assert_patch_order)
        self.assertEqual(LEGACY_MAX_REGISTRY_BYTES, MAX_REGISTRY_BYTES)
        with ledger.locked(self.path) as journal:
            self.assertIsInstance(journal, AppliedHistory)
            self.assertFalse(journal.contains(FIRST))

    def test_history_preserves_legacy_and_structured_records_across_reopen(self):
        self.path.write_text(FIRST + "\n", encoding="utf-8")
        ledger = ProjectPatchLedger()
        stamp = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
        with ledger.locked(self.path) as journal:
            self.assertEqual(journal.entries, [HistoryEntry(FIRST)])
            self.assertFalse(journal.append(FIRST, "feature/old", "main", when=stamp))
            self.assertTrue(journal.append(SECOND, "feature/new", "main", when=stamp))
            self.assertTrue(journal.record_commit_branch(SECOND, "feature/new", "feature/new"))
        entries = parse_history(self.path.read_text(encoding="utf-8"))
        self.assertEqual(entries[0], HistoryEntry(FIRST))
        self.assertEqual(entries[1].planned_branch, "feature/new")
        self.assertEqual(entries[1].real_branch, "feature/new")
        self.assertEqual(entries[1].date, stamp.isoformat(timespec="seconds"))

    def test_registry_is_append_only_and_predecessors_are_required(self):
        ledger = ProjectPatchLedger()
        ordered = (FIRST, SECOND)
        self.assertTrue(ledger.persist_registry(self.root, ordered))
        before = registry_path(self.root).read_bytes()
        self.assertFalse(ledger.persist_registry(self.root, ordered))
        self.assertEqual(read_registry(self.root), ordered)
        with self.assertRaisesRegex(Abort, "cannot be removed or reordered"):
            ledger.persist_registry(self.root, (SECOND,))
        self.assertEqual(registry_path(self.root).read_bytes(), before)
        with ledger.locked(self.path) as journal:
            with self.assertRaisesRegex(Abort, "has not been applied"):
                ledger.assert_order(self.root, SECOND, journal, ordered)
            journal.append(FIRST, "feature/one", "main")
            self.assertTrue(ledger.assert_order(self.root, SECOND, journal, ordered))

    def test_corrupt_history_and_registry_fail_closed_without_rewrite(self):
        self.path.write_text("Date: invalid\nPatch: " + FIRST + "\n", encoding="utf-8")
        original = self.path.read_bytes()
        with self.assertRaises(Abort):
            with locked_history(self.path):
                pass
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(parse_registry(b"", "incoming"), ())
        with self.assertRaisesRegex(Abort, "Duplicate created patch"):
            parse_registry((FIRST + "\n" + FIRST + "\n").encode(), "incoming")
        with self.assertRaisesRegex(Abort, "Cannot read UTF-8"):
            parse_registry(b"\xff", "incoming")
        self.assertFalse(registry_path(self.root).exists())

    def test_registry_rejects_symlink_without_mutating_target(self):
        target = self.root / "protected.txt"
        target.write_text("preserve", encoding="utf-8")
        registry_path(self.root).symlink_to(target)
        with self.assertRaisesRegex(Abort, "symlink"):
            ProjectPatchLedger().persist_registry(self.root, (FIRST,))
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve")

    def test_locked_history_rejects_concurrent_writer(self):
        with locked_history(self.path):
            with self.assertRaises((Abort, BlockingIOError)):
                with locked_history(self.path):
                    pass

    def test_branch_coordinator_consumes_injected_ledger_without_disk_access(self):
        calls = []

        class FakeLedger:
            @contextmanager
            def locked(self, path):
                calls.append(("locked", path))
                yield SimpleNamespace(path=path, contains=lambda _: False)

            def assert_order(self, root, patch_name, history, incoming=None):
                calls.append(("assert_order", root, patch_name, incoming))
                return True

            def persist_registry(self, root, incoming):
                calls.append(("persist_registry", root, incoming))
                return True

        workflow = SimpleNamespace(
            config=SimpleNamespace(applied_patches_path=self.path),
            root=self.root, handoff=SimpleNamespace(patch=SECOND),
            source_handoff=object(),
        )
        actions = BranchPatchActions(workflow, ledger_ops=FakeLedger())
        actions.assert_history_well_formed()
        result = actions.assert_patch_order(
            archive=SimpleNamespace(created_registry=(FIRST, SECOND)))
        self.assertTrue(result)
        self.assertEqual([entry[0] for entry in calls],
                         ["locked", "locked", "assert_order"])
        self.assertEqual(calls[-1][-1], (FIRST, SECOND))


if __name__ == "__main__":
    unittest.main()
