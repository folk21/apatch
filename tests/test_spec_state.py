"""SDD checkpoint validation and developer-approval safety contracts."""

import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.specs.validate_state import ROOT, STATE_PATH, validate_state


class SpecStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    def verify_payload(self, payload: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "STATE.json"
            before = (json.dumps(payload) + "\n").encode("utf-8")
            path.write_bytes(before)
            result = validate_state(path, ROOT)
            self.assertEqual(path.read_bytes(), before)
            return result

    def assert_invalid(self, payload: dict, message: str) -> None:
        with self.assertRaisesRegex(ValueError, message):
            self.verify_payload(payload)

    @staticmethod
    def record(payload: dict, identifier: str) -> dict:
        return next(item for item in payload["workstreams"] if item["id"] == identifier)

    def test_umbrella_has_no_shared_implementation_plan(self) -> None:
        umbrella = ROOT / "docs/specs/umbrella_spec_apatch.md"
        self.assertTrue(umbrella.is_file())
        self.assertIn("APATCH-SPEC-001", umbrella.read_text(encoding="utf-8"))
        self.assertFalse((ROOT / "docs/specs/active/spec-apatch-orchestrator.md").exists())
        self.assertFalse((ROOT / "docs/specs/active/apatch-orchestrator-implementation-plan.md").exists())
        index = (ROOT / "docs/specs/README.md").read_text(encoding="utf-8")
        self.assertIn("umbrella_spec_apatch.md", index)

    def test_current_state_is_valid_read_only_and_focus_is_explicit(self) -> None:
        before = STATE_PATH.read_bytes()
        result = validate_state()
        self.assertEqual(result["selectedWorkstreamId"], "review-evidence")
        self.assertEqual(self.record(result, "review-evidence")["stageId"], "RE-05")
        self.assertEqual({item["id"] for item in result["workstreams"]}, {"review-evidence"})
        self.assertEqual(result["selectedTaskId"], "RE-05")
        self.assertEqual(STATE_PATH.read_bytes(), before)

    def test_cli_reports_selected_focus_without_mutating_source(self) -> None:
        before = STATE_PATH.read_bytes()
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "tools/specs/validate_state.py")],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SDD STATE VALID: review-evidence", result.stdout)
        self.assertEqual(STATE_PATH.read_bytes(), before)

    def test_rejects_unknown_and_missing_root_fields(self) -> None:
        for change in (lambda value: value.update(secret="unexpected"),
                       lambda value: value.pop("mode")):
            with self.subTest(change=change):
                data = copy.deepcopy(self.original)
                change(data)
                self.assert_invalid(data, "Invalid STATE.json fields")

    def test_rejects_unsupported_schema_or_multi_mode(self) -> None:
        for key, bad in (("schemaVersion", True), ("schemaVersion", 2),
                         ("mode", "MULTI")):
            with self.subTest(key=key, bad=bad):
                data = copy.deepcopy(self.original)
                data[key] = bad
                self.assert_invalid(data, "Unsupported schemaVersion|Only SINGLE")

    def test_rejects_missing_selected_record_and_paused_selection(self) -> None:
        data = copy.deepcopy(self.original)
        data["selectedWorkstreamId"] = "missing-focus"
        self.assert_invalid(data, "Selected workstream does not exist")
        data = copy.deepcopy(self.original)
        self.record(data, data["selectedWorkstreamId"])["phase"] = "ON_HOLD"
        self.assert_invalid(data, "Selected workstream cannot be paused")

    def test_rejects_duplicate_ids_or_spec_paths(self) -> None:
        for key in ("id", "specPath"):
            with self.subTest(key=key):
                data = copy.deepcopy(self.original)
                other = copy.deepcopy(data["workstreams"][0])
                if key == "id":
                    other["specPath"] = "docs/specs/active/another-workstream/subspec.md"
                else:
                    other["id"] = "another-workstream"
                data["workstreams"].append(other)
                self.assert_invalid(data, "Duplicate workstream")

    def test_rejects_unknown_phase_extra_fields_and_unselected_ready_stage(self) -> None:
        for key, value, expected in (
            ("phase", "ACCEPTED", "Invalid SDD phase"),
            ("phase", "RUNNING", "Invalid SDD phase"),
            ("phase", 1, "Invalid SDD phase"),
            ("unexpected", True, "Invalid workstream fields"),
            ("stageId", "../FS-01", "Invalid stageId"),
        ):
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(self.original)
                data["workstreams"][0][key] = value
                self.assert_invalid(data, expected)

    def test_spec_lifecycle_has_flat_active_tasks_and_planned_drafts(self) -> None:
        specs = ROOT / "docs/specs"
        active = specs / "active/review-evidence"
        planned = specs / "planned"
        archived = specs / "archive/subspecs"
        self.assertFalse((specs / "plans").exists())
        for stem in ("subspec-01-workflow-control",
                     "subspec-02-state-history-audit",
                     "subspec-05-architectural-simplification"):
            with self.subTest(archived=stem):
                self.assertTrue((archived / f"{stem}.md").is_file())
                self.assertTrue((archived / f"{stem}-implementation-plan.md").is_file())
        for stem in ("subspec-03-feature-session-planning",
                     "subspec-04-operational-workflows"):
            with self.subTest(planned=stem):
                self.assertTrue((planned / f"{stem}.md").is_file())
                self.assertTrue((planned / f"{stem}-implementation-plan.md").is_file())
                self.assertFalse((specs / "active/subspecs" / f"{stem}.md").exists())
        self.assertTrue((active / "subspec.md").is_file())
        self.assertFalse((active / "impl_plan.md").exists())
        self.assertEqual(list(active.glob("task_[0-9][0-9]_*.md")), [])
        plans = sorted(active.glob("task_impl_plan_[0-9][0-9]_*.md"))
        self.assertEqual(len(plans), 7)
        text = (active / "subspec.md").read_text(encoding="utf-8")
        tasks = re.findall(r"(?m)^### (RE-[0-9]{2})$", text)
        self.assertEqual(tasks, [f"RE-{n:02}" for n in range(1, 8)])
        types = re.findall(r"(?m)^- \*\*type:\*\* `([A-Z_]+)`\.$", text)
        areas = re.findall(r"(?m)^- \*\*area:\*\* `([A-Z0-9_]+)`\.$", text)
        self.assertEqual(types, ["GEN_CODE"] * 5 + ["UPD_DOCS", "GEN_TESTS"])
        self.assertEqual(areas, ["BACKEND"] * 5 + ["DOCS", "E2E_TESTS"])
        for number, plan in enumerate(plans, start=1):
            self.assertIn(f"task_impl_plan_{number:02}_", plan.name)
            self.assertIn(f"]({plan.name})", text)
            self.assertIn("subspec.md#re-", plan.read_text(encoding="utf-8"))
        self.assertFalse((ROOT / "docs/DEVELOPMENT.md").exists())
        self.assertFalse((ROOT / "docs/SECURITY.md").exists())
        self.assertFalse(any((specs / "active/subspecs").glob("*.md")))
        self.assertTrue((specs / "AGENTS.md").is_file())

    def test_selected_task_id_is_exact_and_matches_selected_stage(self) -> None:
        for value, expected in (
            ("RE-04", "disagree"),
            ("RE-99", "Missing selected task"),
            ("../RE-05", "Invalid selectedTaskId"),
            (3, "Invalid selectedTaskId"),
        ):
            with self.subTest(value=value):
                data = copy.deepcopy(self.original)
                data["selectedTaskId"] = value
                self.assert_invalid(data, expected)

    def test_task_id_pointer_is_optional_for_existing_checkpoints(self) -> None:
        data = copy.deepcopy(self.original)
        data.pop("selectedTaskId")
        self.assertEqual(self.verify_payload(data)["selectedWorkstreamId"], "review-evidence")

    def test_invalid_task_type_area_or_plan_blocks_checkpoint(self) -> None:
        spec = ROOT / "docs/specs/active/review-evidence/subspec.md"
        source = spec.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            target = temporary_root / "docs/specs/active/review-evidence/subspec.md"
            target.parent.mkdir(parents=True)
            for path in (ROOT / "docs/specs/active/review-evidence").glob("task_impl_plan_*.md"):
                (target.parent / path.name).write_bytes(path.read_bytes())
            features = temporary_root / "docs/FEATURES.md"
            features.parent.mkdir(exist_ok=True, parents=True)
            features.write_bytes((ROOT / "docs/FEATURES.md").read_bytes())
            for replace, expected in (
                ("- **area:** `BACKEND`.", "Invalid task area"),
                ("- **type:** `GEN_CODE`.", "Invalid task type"),
                ("- **Implementation plan:** [RE-05 plan](task_impl_plan_05_retention_export_recovery.md).", "Invalid task plan"),
                ("`REVIEW.RETENTION_EXPORT`", "Invalid feature IDs"),
            ):
                with self.subTest(replace=replace):
                    modified = source.replace(replace, "INVALID", 1)
                    target.write_text(modified, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, expected):
                        self.verify_custom_root(temporary_root)

    def verify_custom_root(self, root: Path) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "STATE.json"
            path.write_text(json.dumps(self.original) + "\n", encoding="utf-8")
            validate_state(path, root)

    def test_sdd_markdown_relative_links_resolve_after_archival(self) -> None:
        specs = ROOT / "docs/specs"
        broken = []
        for document in specs.rglob("*.md"):
            for match in re.finditer(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
                link = match.group(1).split("#", 1)[0]
                if not link or "://" in link or link.startswith(("mailto:", "/")):
                    continue
                if not (document.parent / link).exists():
                    broken.append(f"{document.relative_to(ROOT)} -> {link}")
        self.assertEqual(broken, [])

    def test_rejects_unsafe_missing_and_invalid_spec_paths(self) -> None:
        for path in ("../outside.md", "docs/specs/archive/subspecs/example.md",
                     "docs/specs/planned/subspec-03-feature-session-planning.md",
                     "docs/specs/active/unknown-scope/subspec.md"):
            with self.subTest(path=path):
                data = copy.deepcopy(self.original)
                data["workstreams"][0]["specPath"] = path
                self.assert_invalid(data, "Invalid specPath|Missing or unsafe")

    def test_rejects_duplicate_json_keys_and_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "STATE.json"
            source.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                validate_state(source, ROOT)
            source.write_text('{"schemaVersion":', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid STATE.json"):
                validate_state(source, ROOT)

    def test_rejects_symlinked_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "STATE.json"
            try:
                source.symlink_to(STATE_PATH)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks are unavailable on this platform")
            with self.assertRaisesRegex(ValueError, "regular file"):
                validate_state(source, ROOT)


if __name__ == "__main__":
    unittest.main()