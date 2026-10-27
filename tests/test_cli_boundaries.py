"""AS-04: CLI grammar, read-only selection, and dispatcher boundaries."""

import argparse
import io
import unittest
from contextlib import redirect_stderr
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apatch_lib import application, cli_request, handoff_selection
from apatch_lib.cli_request import parse_request
from apatch_lib.handoff_selection import HandoffSelection, SelectionKind
from apatch_lib.model import Abort, Handoff


def sample_handoff(name: str = "example-PATCH-1.zip") -> Handoff:
    return Handoff(
        repository="example", branch="feature/test", patch=name,
        message="test: typed selection", base_commit=None,
        patch_sha256="a" * 64, delete_paths=())


class CliRequestTests(unittest.TestCase):
    def test_legacy_aliases_and_positional_json_remain_unchanged(self) -> None:
        selected = parse_request(
            ["/tmp/test.json", "opSeq=APL,CHK,STS", "skipApproves=true",
             "verifyRemote=false", "--strict"])
        self.assertEqual(selected.handoff, "/tmp/test.json")
        self.assertEqual(selected.op_seq.actions, (3, 4, 10))
        self.assertEqual(selected.mode, "strict")
        self.assertTrue(selected.skip_approves)
        self.assertFalse(selected.verify_remote)
        self.assertEqual(selected.normalized_arguments[0], "/tmp/test.json")

    def test_request_is_immutable_and_menu_choice_produces_copy(self) -> None:
        request = parse_request([])
        self.assertEqual(request.mode, "loose")
        with self.assertRaises(FrozenInstanceError):
            request.op = "APL"
        selected = request.with_action("STS")
        self.assertEqual(request.op, None)
        self.assertEqual(selected.op, "STS")
        self.assertTrue(selected.status_only)

    def test_invalid_argparse_forms_fail_before_repository_access(self) -> None:
        for args in (["op=INVALID"], ["skipApproves=yes"],
                     ["op=APL", "opSeq=APL,CHK"],
                     ["--strict", "--force"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exit_code:
                    parse_request(args)
                self.assertEqual(exit_code.exception.code, 2)

    def test_semantic_validation_keeps_legacy_recovery_messages(self) -> None:
        examples = (
            (["followup=true", "op=CHK"], "start with APL"),
            (["op=CHK", "patch=sample.zip"], "only supported"),
            (["op=AUD", "patch=sample.zip"], "entire repository"),
            (["opSeq=AUD,STS"], "AUD must run separately"),
            (["op=CHK", "verifyRemote=true"], "only supported"),
        )
        for args, expected in examples:
            with self.subTest(args=args):
                with self.assertRaisesRegex(Abort, expected):
                    cli_request.validate_repository_request(parse_request(args))

    def test_progress_rejects_explicit_lifecycle_flags(self) -> None:
        cli_request.validate_progress_request(parse_request(["info=PROGRESS"]))
        with self.assertRaisesRegex(Abort, "cannot be combined"):
            cli_request.validate_progress_request(
                parse_request(["info=PROGRESS", "skipApproves=false"]))


class HandoffSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("/isolated/project")
        self.config = SimpleNamespace(downloads=Path("/isolated/downloads"))

    def test_cache_and_explicit_legacy_selection_preserve_provenance(self) -> None:
        handoff = sample_handoff()
        with patch.object(handoff_selection, "load_cached_handoff", return_value=handoff):
            selected = handoff_selection.resolve_selected_handoff(None, self.config, self.root)
        self.assertEqual(selected.kind, SelectionKind.CACHED_WORKFLOW)
        self.assertFalse(selected.zip_selected)
        with patch.object(handoff_selection, "load_handoff", return_value=handoff):
            legacy = handoff_selection.resolve_selected_handoff(
                "legacy.json", self.config, self.root)
        self.assertEqual(legacy.kind, SelectionKind.LEGACY_JSON)
        self.assertEqual(legacy.source_label, "/isolated/downloads/legacy.json")

    def test_zip_provenance_is_distinct_from_permission_to_replay(self) -> None:
        handoff = sample_handoff()
        with patch.object(handoff_selection, "handoff_from_zip", return_value=handoff):
            selected = handoff_selection.resolve_selected_handoff(
                "example-PATCH-1", self.config, self.root)
        self.assertEqual(selected.kind, SelectionKind.NEW_ZIP)
        self.assertEqual(selected.required_next_step, "APL")
        applied = selected.with_existing_record(
            {"phase": "patch_applied", "archive_sha256": handoff.patch_sha256})
        self.assertEqual(applied.kind, SelectionKind.APPLIED_ZIP)
        self.assertTrue(applied.zip_selected)
        self.assertEqual(selected.kind, SelectionKind.NEW_ZIP)
        conflict = selected.with_existing_record(
            {"phase": "patch_applied", "archive_sha256": "b" * 64})
        self.assertEqual(conflict.kind, SelectionKind.CONFLICT)
        self.assertFalse(conflict.zip_selected)
        self.assertEqual(conflict.required_next_step, "STS")

    def test_sequence_resolution_validates_all_members_before_dispatch(self) -> None:
        request = parse_request(
            ["opSeq=APL,BRN,APL,CHK", "handoffSeq=first.zip,second.zip"])
        with patch.object(handoff_selection, "handoff_from_zip",
                          side_effect=[sample_handoff("first.zip"),
                                       sample_handoff("second.zip")]) as reader:
            selected = handoff_selection.resolve_handoffs(
                request, self.config, self.root)
        self.assertEqual(selected.kind, SelectionKind.NEW_ZIP)
        self.assertEqual(tuple(h.patch for h in selected.sequence),
                         ("first.zip", "second.zip"))
        self.assertEqual(reader.call_count, 2)

    def test_zip_path_escape_is_rejected_before_archive_read(self) -> None:
        with patch.object(handoff_selection, "handoff_from_zip") as loader:
            with self.assertRaises(Abort):
                handoff_selection.resolve_sequence_zip_names(
                    "../../unsafe.zip", self.config)
            loader.assert_not_called()


class ApplicationBoundaryTests(unittest.TestCase):
    def test_unverified_zip_start_does_not_enable_branch_recovery(self) -> None:
        handoff = sample_handoff()
        context = SimpleNamespace(
            root=Path("/isolated/example"),
            config=SimpleNamespace(base="main", state_path=Path("/unused/state")))
        selection = HandoffSelection(handoff, "test.zip", SelectionKind.NEW_ZIP)
        saved = {"workflows": {
            "the key": {"phase": "patch_applied", "zip_first": True,
                        "applied_branch": "main", "archive_sha256": "b" * 64}}}
        with patch.object(application, "read_state_snapshot", return_value=saved), \
                patch.object(application, "workflow_key", return_value="the key"):
            with self.assertRaisesRegex(Abort, "must start with op=APL"):
                application._admit_zip_start(
                    parse_request(["op=BRN"]), context, selection)

    def test_matching_zip_first_checkpoint_allows_cache_recovery(self) -> None:
        handoff = sample_handoff()
        context = SimpleNamespace(
            root=Path("/isolated/example"),
            config=SimpleNamespace(base="main", state_path=Path("/unused/state")))
        selection = HandoffSelection(handoff, "test.zip", SelectionKind.NEW_ZIP)
        saved = {"workflows": {
            "the key": {"phase": "patch_applied", "zip_first": True,
                        "applied_branch": "main",
                        "archive_sha256": handoff.patch_sha256}}}
        with patch.object(application, "read_state_snapshot", return_value=saved), \
                patch.object(application, "workflow_key", return_value="the key"):
            self.assertTrue(application._admit_zip_start(
                parse_request(["op=BRN"]), context, selection))

    def test_global_progress_exits_before_repository_bootstrap(self) -> None:
        config = SimpleNamespace(progress_global_limit=8, progress_project_limit=3)
        with patch.object(application, "load_config", return_value=config), \
                patch.object(application, "ProgressStore") as store, \
                patch.object(application, "render_progress", return_value="No history"), \
                patch.object(application, "_resolve_project") as resolve, \
                patch("builtins.print"):
            store.return_value.read_snapshot.return_value = {}
            self.assertEqual(application.execute_request(
                parse_request(["info=PROGRESS"]), Path("/tool")), 0)
            resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
