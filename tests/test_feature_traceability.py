"""Document-level feature identity and source ownership validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.specs.validate_features import ROOT, validate_features


class FeatureTraceabilityTests(unittest.TestCase):
    def test_catalog_and_cross_reference_link_real_source_and_tests(self) -> None:
        entries = validate_features()
        self.assertGreaterEqual(len(entries), 10)
        by_id = {row["feature_id"]: row for row in entries}
        self.assertEqual(len(by_id), len(entries))
        self.assertEqual(by_id["REVIEW.RETENTION_EXPORT"]["stages"], ["RE-05"])
        self.assertIn("docs/specs/archive/workstreams/review-evidence/subspec.md",
                      by_id["REVIEW.RETENTION_EXPORT"]["spec_paths"])
        self.assertEqual(by_id["REVIEW.RETENTION_EXPORT"]["implementation_status"], "partial")

    def test_schema_matches_melliatlas_style_without_runtime_id_field(self) -> None:
        schema = json.loads((ROOT / "docs/specs/feature-cross-ref.schema.json").read_text())
        record = schema["properties"]["features"]["items"]
        self.assertEqual(schema["properties"]["schema_version"]["const"], 2)
        self.assertEqual(record["properties"]["implementation_status"]["enum"],
                         ["planned", "partial", "verified"])
        self.assertEqual(set(record["required"]),
                         {"feature_id", "implementation_status", "stages", "spec_paths",
                          "owners", "test_files"})

    def test_schema_accepts_umbrella_path_without_legacy_parent(self) -> None:
        import re

        schema = json.loads((ROOT / "docs/specs/feature-cross-ref.schema.json").read_text())
        pattern = schema["properties"]["features"]["items"]["properties"]["spec_paths"]["items"]["pattern"]
        self.assertIsNotNone(re.fullmatch(pattern, "docs/specs/umbrella_spec_apatch.md"))
        self.assertIsNone(re.fullmatch(pattern, "docs/specs/active/spec-apatch-orchestrator.md"))

    def test_unknown_and_duplicate_feature_identity_is_rejected(self) -> None:
        source = (ROOT / "docs/specs/feature-cross-ref.yaml").read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feature-cross-ref.yaml"
            for text, expected in (
                (source.replace("REVIEW.RAW_CAPTURE", "REVIEW.NOT_IN_CATALOG", 1),
                 "unknown feature ID"),
                (source.replace("schema_version: 2", "schema_version: 3", 1),
                 "Unsupported feature schema"),
                (source.replace("schema_version: 2", "schema_version: 2\nschema_version: 2", 1),
                 "duplicate YAML"),
            ):
                with self.subTest(expected=expected):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, expected):
                        validate_features(path)

    def test_invalid_owner_and_stale_stage_are_rejected(self) -> None:
        source = (ROOT / "docs/specs/feature-cross-ref.yaml").read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feature-cross-ref.yaml"
            for text, expected in (
                (source.replace("apatch_lib/review_retention.py", "apatch_lib/missing.py", 1),
                 "Missing or unsafe feature path"),
                (source.replace("- RE-05", "- RE-99", 1),
                 "Stage is absent"),
                (source.replace("- tests/test_review_retention.py", "- ../outside.py", 1),
                 "Invalid test_files"),
            ):
                with self.subTest(expected=expected):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, expected):
                        validate_features(path)


if __name__ == "__main__":
    unittest.main()