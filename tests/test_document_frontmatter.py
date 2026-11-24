"""Minimal OKF front matter and normative task routing regression tests."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tools.specs.validate_docs import (ROOT, parse_header, repository_markdown,
                                       validate_documents)


class DocumentFrontmatterTests(unittest.TestCase):
    def _copy_documents(self, destination: Path) -> None:
        for file in repository_markdown(ROOT):
            target = destination / file.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)

    def test_all_repository_markdown_has_minimal_metadata(self) -> None:
        documents = validate_documents()
        actual = {path.relative_to(ROOT).as_posix() for path in repository_markdown(ROOT)}
        self.assertEqual(set(documents), actual)
        self.assertEqual(len(documents), 35)
        plans = {name: info for name, info in documents.items()
                 if Path(name).name.startswith("task_impl_plan_")}
        self.assertEqual(len(plans), 7)
        for name, info in documents.items():
            self.assertEqual(set(info), {"type", "title", "description"} | (
                {"area", "runType"} if name in plans else set()))

    def test_runtime_backup_markdown_is_outside_validation_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)
            self._copy_documents(clone)
            for runtime in (
                ".apatch/backups/overlap-sample/apatch_lib/handoff/contract.md",
                ".venv/lib/python/site-packages/example/README.md",
                "build/temporary/README.md",
                "logs/old/README.md",
            ):
                backup = clone / runtime
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_text("# Historical copy without OKF metadata\n", encoding="utf-8")
            documents = validate_documents(clone)
            self.assertEqual(len(documents), 35)
            self.assertTrue(all(not name.startswith((".apatch/", ".venv/", "build/", "logs/"))
                                for name in documents))

            source = clone / "docs/new_guide.md"
            source.write_text("# New source document without OKF metadata\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing OKF front matter"):
                validate_documents(clone)

    def test_task_routing_fields_match_normative_tasks(self) -> None:
        docs = validate_documents()
        plans = {name: info for name, info in docs.items()
                 if Path(name).name.startswith("task_impl_plan_")}
        self.assertEqual(len(plans), 7)
        for number in range(1, 8):
            name, info = next((name, info) for name, info in plans.items()
                              if Path(name).name.startswith(f"task_impl_plan_{number:02d}_"))
            self.assertEqual(info["type"],
                             "GEN_CODE" if number <= 5 else "UPD_DOCS" if number == 6 else "GEN_TESTS")
            self.assertEqual(info["area"],
                             "CODE" if number <= 5 else "DOCS" if number == 6 else "E2E_TESTS")
            self.assertEqual(info["runType"], "ACCEPT" if number == 7 else "DEVELOP")
            self.assertNotIn("feature_ids", info)
            self.assertNotIn("task_id", info)
            self.assertNotIn("parent", info)

    def test_duplicate_keys_missing_fields_and_title_drift_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "sample.md"
            valid = "---\ntype: Usage Guide\ntitle: Example\ndescription: Example document\n---\n# Example\n"
            for content, pattern in (
                ("# Example\n", "Missing OKF"),
                (valid.replace("description:", "type: Usage Guide\ndescription:"), "Duplicate"),
                (valid.replace("# Example", "# Different"), "title differs"),
                (valid.replace("description: Example document\n", ""), "Missing OKF"),
                (valid.replace("---\n# Example", "status: draft\n---\n# Example"),
                 "Unexpected or missing OKF fields"),
            ):
                with self.subTest(pattern=pattern):
                    file.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, pattern):
                        parse_header(file)

    def test_task_header_rejects_missing_or_extra_routing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)
            self._copy_documents(clone)
            target = clone / "docs/specs/archive/workstreams/review-evidence/task_impl_plan_05_retention_export_recovery.md"
            original = target.read_text(encoding="utf-8")
            for altered, pattern in (
                (original.replace("area: CODE\n", "area: DOCS\n", 1), "routing disagrees"),
                (original.replace("runType: DEVELOP\n", "runType: ACCEPT\n", 1), "routing disagrees"),
                (original.replace("type: GEN_CODE\n", "type: GEN_TESTS\n", 1), "routing disagrees"),
                (original.replace("runType: DEVELOP\n", "", 1), "Unexpected or missing OKF fields"),
                (original.replace("runType: DEVELOP\n", "runType: DEVELOP\nfeature_ids: []\n", 1),
                 "Unexpected or missing OKF fields"),
            ):
                with self.subTest(pattern=pattern):
                    target.write_text(altered, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, pattern):
                        validate_documents(clone)
            target.write_text(original, encoding="utf-8")
            self.assertEqual(len(validate_documents(clone)), 35)

    def test_normative_task_type_area_rtype_and_features_are_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)
            self._copy_documents(clone)
            target = clone / "docs/specs/archive/workstreams/review-evidence/subspec.md"
            original = target.read_text(encoding="utf-8")
            for altered, pattern in (
                (original.replace("- **area:** `CODE`.", "- **area:** `DOCS`.", 1),
                 "normative task type/area"),
                (original.replace("- **rtype:** `DEVELOP`.", "- **rtype:** `ACCEPT`.", 1),
                 "Invalid normative rtype"),
                (original.replace("`REVIEW.RAW_CAPTURE`", "`REVIEW.UNLISTED`", 1),
                 "Invalid normative feature_ids"),
                (original.replace("[RE-01 plan](task_impl_plan_01_raw_evidence_capture.md)",
                                  "[RE-01 plan](task_impl_plan_02_structured_normalization.md)", 1),
                 "Task plan filename disagrees"),
            ):
                with self.subTest(pattern=pattern):
                    target.write_text(altered, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, pattern):
                        validate_documents(clone)
            target.write_text(original, encoding="utf-8")
            self.assertEqual(len(validate_documents(clone)), 35)


if __name__ == "__main__":
    unittest.main()
