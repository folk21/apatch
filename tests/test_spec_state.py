"""SDD checkpoint validation and developer-approval safety contracts."""

import copy
import json
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

    def test_current_state_is_valid_read_only_and_focus_is_explicit(self) -> None:
        before = STATE_PATH.read_bytes()
        result = validate_state()
        self.assertEqual(result["selectedWorkstreamId"], "feature-sessions")
        self.assertEqual(next(w for w in result["workstreams"]
                              if w["id"] == "feature-sessions")["stageId"], "FS-01")
        self.assertEqual(STATE_PATH.read_bytes(), before)

    def test_cli_reports_selected_focus_without_mutating_source(self) -> None:
        before = STATE_PATH.read_bytes()
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "tools/specs/validate_state.py")],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SDD STATE VALID: feature-sessions", result.stdout)
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
        data["workstreams"][2]["phase"] = "ON_HOLD"
        self.assert_invalid(data, "Selected workstream cannot be paused")

    def test_rejects_duplicate_ids_or_spec_paths(self) -> None:
        for key in ("id", "specPath"):
            with self.subTest(key=key):
                data = copy.deepcopy(self.original)
                data["workstreams"][1][key] = data["workstreams"][0][key]
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
        data = copy.deepcopy(self.original)
        data["workstreams"][0]["phase"] = "READY_FOR_IMPLEMENTATION"
        self.assert_invalid(data, "Only the selected SINGLE")

    def test_rejects_unsafe_missing_and_invalid_spec_paths(self) -> None:
        for path in ("../outside.md", "docs/specs/archive/subspecs/example.md",
                     "docs/specs/active/subspecs/subspec-99-missing.md"):
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
