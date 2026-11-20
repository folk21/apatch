"""OKF metadata coverage and task-plan traceability regression tests."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tools.specs.validate_docs import (ROOT, parse_header, repository_markdown,
                                       validate_documents)


class DocumentFrontmatterTests(unittest.TestCase):
    def test_all_repository_markdown_has_checked_metadata(self) -> None:
        documents = validate_documents()
        actual = {path.relative_to(ROOT).as_posix() for path in repository_markdown(ROOT)}
        self.assertEqual(set(documents), actual)
        self.assertEqual(len(documents), 35)
        self.assertEqual(documents["docs/specs/umbrella_spec_apatch.md"]["document_role"],
                         "umbrella")
        self.assertNotIn("parent", documents["docs/specs/umbrella_spec_apatch.md"])

    def test_runtime_backup_markdown_is_outside_validation_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)
            for file in repository_markdown(ROOT):
                destination = clone / file.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, destination)
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

            real_document = clone / "docs/new_guide.md"
            real_document.write_text("# Real source document without OKF metadata\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing OKF front matter"):
                validate_documents(clone)

    def test_all_task_types_areas_run_types_and_features_are_explicit(self) -> None:
        documents = validate_documents()
        plans = {info["task_id"]: info for info in documents.values()
                 if info.get("document_role") == "task_plan"}
        self.assertEqual(set(plans), {f"RE-{number:02d}" for number in range(1, 8)})
        for number in range(1, 8):
            info = plans[f"RE-{number:02d}"]
            self.assertEqual(info["type"], "Implementation Guide")
            self.assertEqual(info["parent"], "subspec.md")
            self.assertEqual(info["plan_status"], "advisory")
            self.assertTrue(info["feature_ids"])
            self.assertEqual(info["task_type"],
                             "GEN_CODE" if number <= 5 else "UPD_DOCS" if number == 6 else "GEN_TESTS")
            self.assertEqual(info["area"],
                             "CODE" if number <= 5 else "DOCS" if number == 6 else "E2E_TESTS")
            self.assertEqual(info["rtype"], "ACCEPT" if number == 7 else "DEVELOP")

    def test_duplicate_keys_missing_frontmatter_and_title_drift_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "sample.md"
            valid = "---\ntype: Usage Guide\ntitle: Example\ndescription: Example document\n---\n# Example\n"
            for content, pattern in (
                ("# Example\n", "Missing OKF"),
                (valid.replace("description:", "type: Usage Guide\ndescription:"), "Duplicate"),
                (valid.replace("# Example", "# Different"), "title differs"),
                (valid.replace("description: Example document\n", ""), "Missing OKF"),
            ):
                with self.subTest(pattern=pattern):
                    file.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, pattern):
                        parse_header(file)

    def test_changed_task_header_cannot_claim_wrong_area_or_run_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)
            for file in repository_markdown(ROOT):
                destination = clone / file.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, destination)
            target = clone / "docs/specs/active/review-evidence/task_impl_plan_05_retention_export_recovery.md"
            original = target.read_text(encoding="utf-8")
            for altered, pattern in (
                (original.replace("area: CODE\n", "area: DOCS\n", 1), "task_type/area"),
                (original.replace("rtype: DEVELOP\n", "rtype: ACCEPT\n", 1), "rtype"),
                (original.replace("REVIEW.RETENTION_EXPORT", "REVIEW.NOT_A_FEATURE", 1), "feature_ids"),
                (original.replace("task_type: GEN_CODE", "task_type: GEN_TESTS", 1), "task_type/area"),
            ):
                with self.subTest(pattern=pattern):
                    target.write_text(altered, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, pattern):
                        validate_documents(clone)
            target.write_text(original, encoding="utf-8")
            self.assertEqual(len(validate_documents(clone)), 35)

    def test_task_header_must_match_normative_subspec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)
            for file in repository_markdown(ROOT):
                destination = clone / file.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, destination)
            target = clone / "docs/specs/active/review-evidence/subspec.md"
            source = target.read_text(encoding="utf-8")
            target.write_text(source.replace("- **area:** `CODE`.", "- **area:** `DOCS`.", 1),
                              encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "disagrees with normative"):
                validate_documents(clone)


if __name__ == "__main__":
    unittest.main()
