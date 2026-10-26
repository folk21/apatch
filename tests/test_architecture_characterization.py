"""AS-01 characterization and AS-02 validated-boundary regression contracts.

Expected failures document observed defects. Remove each marker when its owning
stage implements and verifies the stricter behavior; do not weaken the assertion.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apatch_lib import github
from apatch_lib.model import Abort, RemoteOutcomeUnknown
from apatch_lib.state import locked_state, read_state_snapshot, save
from apatch_lib.status import recommend_next_action
from tests._support import LocalGitFixture, command


class StatusPolicyCharacterizationTests(unittest.TestCase):
    def test_existing_phase_recommendations_remain_stable(self) -> None:
        cases = (
            ("patch_applied", 4),
            ("verified", 5),
            ("committed", 6),
            ("pushed", 7),
            ("pr_created", 8),
            ("merged", 9),
            ("synced", None),
        )
        for phase, expected in cases:
            with self.subTest(phase=phase):
                next_action, _, _ = recommend_next_action(
                    phase, "loose", "feature/example", "feature/example",
                    base="main", dirty=False,
                )
                self.assertEqual(next_action, expected)

    def test_zip_first_pending_branch_recommends_brn(self) -> None:
        number, alternative, _ = recommend_next_action(
            "patch_applied", "loose", "main", "feature/example",
            base="main", zip_pending_branch=True,
        )
        self.assertEqual((number, alternative), (1, None))

    def test_conflicted_workflow_does_not_suggest_publication(self) -> None:
        for phase in ("new", "verified", "pr_created"):
            with self.subTest(phase=phase):
                number, alternate, reason = recommend_next_action(
                    phase, "loose", "main", "feature/example", conflict=True,
                )
                self.assertIsNone(number)
                self.assertIsNone(alternate)
                self.assertIn("reconcile", reason.lower())

    @unittest.expectedFailure
    def test_new_self_contained_zip_should_recommend_apl_before_brn(self) -> None:
        # AS-05: The current phase-only policy incorrectly recommends BRN first.
        number, _, _ = recommend_next_action(
            "new", "loose", "main", "feature/example",
            base="main", dirty=False,
        )
        self.assertEqual(number, 3)


class StateBoundaryCharacterizationTests(unittest.TestCase):
    def test_legacy_state_read_is_pure_and_authorized_write_keeps_unknowns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            old = {"schema_version": 1, "workflows": {},
                   "future_extension": {"identifier": "preserve-me"}}
            before = (json.dumps(old, sort_keys=True) + "\n").encode("utf-8")
            path.write_bytes(before)

            snapshot = read_state_snapshot(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(snapshot["schema_version"], 2)
            self.assertEqual(snapshot["operation_runs"], [])
            self.assertEqual(snapshot["future_extension"], old["future_extension"])

            with locked_state(path) as writable:
                save(path, writable)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], 2)
            self.assertEqual(saved["future_extension"], old["future_extension"])

    def test_invalid_root_is_rejected_without_replacing_state_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            contents = b'{"schema_version":2,"workflows":[]}'
            path.write_bytes(contents)
            with self.assertRaises(Abort):
                read_state_snapshot(path)
            self.assertEqual(path.read_bytes(), contents)

    def test_nested_non_mapping_workflow_should_fail_with_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            contents = b'{"schema_version":2,"workflows":{"bad":[]},"operation_runs":[]}'
            path.write_bytes(contents)
            with self.assertRaises(Abort):
                read_state_snapshot(path)
            self.assertEqual(path.read_bytes(), contents)

    def test_known_workflow_field_types_are_rejected_without_writes(self) -> None:
        corrupt_records = (
            {"repository": ["/repo"]},
            {"phase": {"value": "verified"}},
            {"pr_number": True},
            {"changed_paths": ["ok.txt", 21]},
            {"zip_first": "true"},
            {"remote_before_patch_head": []},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            for record in corrupt_records:
                with self.subTest(record=record):
                    contents = json.dumps({"schema_version": 2,
                                           "workflows": {"old": record},
                                           "operation_runs": []}).encode()
                    path.write_bytes(contents)
                    with self.assertRaises(Abort):
                        read_state_snapshot(path)
                    self.assertEqual(path.read_bytes(), contents)

    def test_known_fields_and_forward_extensions_survive_legacy_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            workflow = {"repository": "/old/repository", "phase": "patch_applied",
                        "remote_before_patch_head": None, "loose_backup": None,
                        "future_stage": {"tags": ["alpha", 2]}}
            original = {"schema_version": 1, "workflows": {"old": workflow},
                        "future_root": {"unknown": True}}
            before = json.dumps(original).encode()
            path.write_bytes(before)
            snapshot = read_state_snapshot(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(snapshot["workflows"]["old"], workflow)
            with locked_state(path) as writable:
                save(path, writable)
            result = json.loads(path.read_text())
            self.assertEqual(result["workflows"]["old"], workflow)
            self.assertEqual(result["future_root"], original["future_root"])


class GithubBoundaryCharacterizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SimpleNamespace(base="main", github_timeout_seconds=1)
        self.root = Path("/unused-mocked-repository")
        self.branch = "feature/example"
        self.pr = {
            "number": 4, "state": "OPEN", "headRefName": self.branch,
            "baseRefName": "main", "headRefOid": "a" * 40,
            "url": "https://github.com/example/repo/pull/4", "mergedAt": None,
        }

    def test_existing_pr_filter_uses_exact_head_and_configured_base(self) -> None:
        other_base = dict(self.pr, number=5, baseRefName="develop",
                          url="https://github.com/example/repo/pull/5")
        other_head = dict(self.pr, number=6, headRefName="feature/unrelated",
                          url="https://github.com/example/repo/pull/6")
        with patch.object(github, "gh_output", return_value=json.dumps(
            [self.pr, other_base, other_head],
        )) as gh_read:
            default = github.pr_list(
                self.config, self.root, "example/repo", self.branch,
            )
            all_bases = github.pr_list(
                self.config, self.root, "example/repo", self.branch,
                include_other_bases=True,
            )
        self.assertEqual([item["number"] for item in default], [4])
        self.assertEqual([item["number"] for item in all_bases], [4, 5])
        self.assertEqual(gh_read.call_count, 2)

    def test_transient_read_is_retried_once_with_bounded_delay(self) -> None:
        with patch.object(github, "output", side_effect=[Abort("HTTP 504"), "[]"]) as read, \
                patch.object(github.time, "sleep") as pause:
            self.assertEqual(github.gh_output(
                self.config, self.root,
                ["gh", "pr", "list", "--repo", "example/repo"],
            ), "[]")
        self.assertEqual(read.call_count, 2)
        pause.assert_called_once()

    def test_permanent_authentication_error_is_not_retried(self) -> None:
        with patch.object(github, "output", side_effect=Abort("HTTP 403")) as read, \
                patch.object(github.time, "sleep") as pause:
            with self.assertRaises(Abort):
                github.gh_output(self.config, self.root, ["gh", "pr", "view", "4"])
        read.assert_called_once()
        pause.assert_not_called()

    def test_uncertain_remote_mutation_is_not_replayed(self) -> None:
        with patch.object(github, "run", side_effect=Abort("HTTP 504")) as mutate:
            with self.assertRaises(RemoteOutcomeUnknown):
                github.gh_run(self.config, self.root, ["gh", "pr", "create"])
        mutate.assert_called_once()

    def test_pr_list_non_list_json_should_raise_domain_error(self) -> None:
        with patch.object(github, "gh_output", return_value='{"unexpected":true}'):
            with self.assertRaises(Abort):
                github.pr_list(self.config, self.root, "example/repo", self.branch)

    def test_pr_details_bad_json_should_raise_domain_error(self) -> None:
        with patch.object(github, "gh_output", return_value="not-json"):
            with self.assertRaises(Abort):
                github.pr_details(self.config, self.root, "example/repo", 4)

    def test_pr_list_rejects_corrupt_items_without_reinterpreting_them_as_empty(self) -> None:
        invalid = (
            [None],
            [dict(self.pr, number=True)],
            [dict(self.pr, state=["OPEN"])],
            [dict(self.pr, headRefName=None)],
            [dict(self.pr, headRefOid=["a" * 40])],
            [dict(self.pr, url="https://github.com/other/repo/pull/4")],
            [dict(self.pr, number=4, headRefName="bad\nbranch")],
        )
        for items in invalid:
            with self.subTest(items=items), \
                    patch.object(github, "gh_output", return_value=json.dumps(items)):
                with self.assertRaises(Abort):
                    github.pr_list(self.config, self.root, "example/repo", self.branch)

    def test_pr_details_rejects_bad_checks_and_mismatched_number(self) -> None:
        valid = dict(self.pr, reviewDecision=None, mergeable="MERGEABLE",
                     mergeStateStatus="CLEAN", statusCheckRollup=None)
        with patch.object(github, "gh_output", return_value=json.dumps(valid)):
            self.assertEqual(github.pr_details(
                self.config, self.root, "example/repo", 4,
            )["number"], 4)
        invalid = (
            dict(valid, statusCheckRollup={"checks": []}),
            dict(valid, statusCheckRollup=["success"]),
            dict(valid, statusCheckRollup=[{"conclusion": 1}]),
            dict(valid, number=5),
        )
        for item in invalid:
            with self.subTest(item=item), \
                    patch.object(github, "gh_output", return_value=json.dumps(item)):
                with self.assertRaises(Abort):
                    github.pr_details(self.config, self.root, "example/repo", 4)

    def test_bounded_pr_json_and_malformed_unicode_raise_abort(self) -> None:
        for raw in ("[" + " " * (8 * 1024 * 1024) + "]", '"\\ud800"', "{}"):
            with self.subTest(size=len(raw)):
                with self.assertRaises(Abort):
                    github.decode_pr_list(raw)

    def test_audit_remote_list_shares_pr_validator_before_git_inspection(self) -> None:
        from apatch_lib import reconciliation

        config = SimpleNamespace(remote="origin", github_timeout_seconds=1)
        invalid = json.dumps([dict(self.pr, number="4")])
        with patch.object(github, "repository", return_value="example/repo"), \
                patch.object(github, "gh_output", return_value=invalid), \
                patch.object(reconciliation, "_git") as git_read:
            with self.assertRaises(Abort):
                reconciliation._remote_snapshot(config, self.root)
            git_read.assert_not_called()


class SequenceOutcomeCharacterizationTests(LocalGitFixture):
    def test_cancelled_apl_stops_sequence_without_extracting_files(self) -> None:
        stem = self.make_self_contained_zip()
        before_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout
        before_source = (self.root / "existing.txt").read_bytes()
        result = self.invoke_zip(
            "opSeq=APL,BRN,CHK", selection=stem, text="NO\n",
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("CANCELLED", result.stdout)
        self.assertIn("SEQUENCE STOP", result.stdout)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout,
                         before_head)
        self.assertEqual((self.root / "existing.txt").read_bytes(), before_source)
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.history_path.exists())
