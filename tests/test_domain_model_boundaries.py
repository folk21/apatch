"""R2.2 import, model, and metadata contract regression checks."""

import ast
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from apatch_lib import model
from apatch_lib.core.api import Abort
from apatch_lib.core.contracts import (ActionResult, GitHubPr, GitHubPrIdentity)
from apatch_lib.handoff import api as handoff
from apatch_lib.handoff import constants, models as handoff_models, parsing
from apatch_lib.publication import api as publication
from apatch_lib.publication import errors as publication_errors, models as publication_models


class DomainModelBoundaryTests(unittest.TestCase):
    def test_historical_handoff_identifiers_are_identity_aliases(self):
        historical = (
            (model.Handoff, handoff.Handoff),
            (model.load_handoff, handoff.load_handoff),
            (model.parse_handoff_payload, handoff.parse_handoff_payload),
            (model.safe_relative, handoff.safe_relative),
            (model.BASENAME_PATTERN, handoff.BASENAME_PATTERN),
            (model.BRANCH_PATTERN, handoff.BRANCH_PATTERN),
            (model.SHA_PATTERN, handoff.SHA_PATTERN),
            (model.DIGEST_PATTERN, handoff.DIGEST_PATTERN),
        )
        for old, new in historical:
            with self.subTest(name=getattr(old, '__name__', repr(old))):
                self.assertIs(old, new)

    def test_publication_errors_and_pr_views_keep_exact_old_type_identity(self):
        self.assertIs(model.RemoteOutcomeUnknown, publication.RemoteOutcomeUnknown)
        self.assertIs(publication_errors.RemoteOutcomeUnknown, publication.RemoteOutcomeUnknown)
        self.assertIs(GitHubPr, publication.GitHubPr)
        self.assertIs(GitHubPrIdentity, publication.GitHubPrIdentity)
        self.assertEqual(publication.GitHubPr.__module__, "apatch_lib.publication.models")
        self.assertEqual(publication.GitHubPrIdentity.__module__, "apatch_lib.publication.models")
        self.assertTrue(issubclass(model.RemoteOutcomeUnknown, Abort))
        self.assertTrue(issubclass(model.RemoteOutcomeUnknown, RuntimeError))
        self.assertEqual(ActionResult.failed(
            publication.RemoteOutcomeUnknown("HTTP timeout"), declined=True
        ).outcome.value, "UNKNOWN_REMOTE_RESULT")
        self.assertEqual(ActionResult.failed(
            Abort("local failure"), declined=False
        ).outcome.value, "ERROR")

    def test_handoff_is_immutable_and_has_unchanged_subject(self):
        self.assertEqual(handoff_models.Handoff.__module__, "apatch_lib.handoff.models")
        self.assertTrue(dataclasses.is_dataclass(handoff.Handoff))
        self.assertTrue(handoff.Handoff.__dataclass_params__.frozen)
        value = handoff.Handoff("service", "feature/new", "patch.zip",
                                "feat: subject\n\nMore details\n", None, None, ())
        self.assertEqual(value.subject, "feat: subject")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.branch = "feature/changed"

    def test_embedded_and_legacy_payloads_preserve_normalization(self):
        metadata = {
            "schema_version": 1,
            "repository": "service",
            "feature_branch": "feature/branch",
            "patch_file": "service-PATCH-123.zip",
            "commit_message": "fix: valid\n\nbody  \n",
            "delete_paths": ["old.txt", "nested/old.py"],
        }
        embedded = handoff.parse_handoff_payload(metadata, embedded=True)
        self.assertIsInstance(embedded, handoff_models.Handoff)
        self.assertEqual(embedded.message, "fix: valid\n\nbody\n")
        self.assertEqual(embedded.delete_paths, ("old.txt", "nested/old.py"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            legacy = {**metadata, "patch_sha256": "b" * 64, "base_commit": "a" * 40}
            path.write_text(json.dumps(legacy), encoding="utf-8")
            parsed = handoff.load_handoff(path)
            self.assertEqual(parsed.patch_sha256, "b" * 64)
            self.assertEqual(parsed.base_commit, "a" * 40)
            self.assertEqual(parsed.message, embedded.message)
            with self.assertRaisesRegex(Abort, "must not contain"):
                handoff.parse_handoff_payload(legacy, embedded=True)

    def test_untrusted_metadata_rejections_are_preserved(self):
        source = {
            "schema_version": 1, "repository": "service",
            "feature_branch": "feature/valid", "patch_file": "valid.zip",
            "commit_message": "feat: valid",
        }
        for change, message in (
            ({"schema_version": 2}, "schema_version"),
            ({"unexpected_field": 1}, "Unknown handoff keys"),
            ({"repository": "../escape"}, "Invalid repository"),
            ({"feature_branch": "feature/../evil"}, "Invalid feature_branch"),
            ({"patch_file": "../evil.zip"}, "ZIP basename"),
            ({"commit_message": "\n"}, "commit_message"),
            ({"commit_message": "x" * 8193}, "commit_message"),
            ({"base_commit": "a" * 39}, "full lowercase Git SHA"),
            ({"patch_sha256": "g" * 64}, "lowercase SHA-256"),
            ({"delete_paths": ["../secret.txt"]}, "Unsafe path"),
            ({"delete_paths": [".git/config"]}, "Unsafe path"),
            ({"delete_paths": "not a list"}, "list of repository-relative"),
        ):
            with self.subTest(change=change):
                with self.assertRaisesRegex(Abort, message):
                    handoff.parse_handoff_payload({**source, **change})
        for unsafe in ("../a", ".git/config", "a\\b", "a//b", "a/./b", "/absolute"):
            with self.subTest(path=unsafe), self.assertRaises(Abort):
                handoff.safe_relative(unsafe)

    def test_invalid_json_does_not_modify_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            path.write_text("{broken", encoding="utf-8")
            original = path.read_bytes()
            with self.assertRaisesRegex(Abort, "Cannot read handoff JSON"):
                handoff.load_handoff(path)
            self.assertEqual(path.read_bytes(), original)

    def test_domain_model_modules_have_no_effectful_top_level_definitions(self):
        for module in (handoff_models, publication_models, publication_errors):
            with self.subTest(module=module.__name__):
                tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
                imported = [node.module or "" for node in tree.body
                            if isinstance(node, ast.ImportFrom)]
                self.assertFalse(any(name.endswith("gitutil") or
                                     name.endswith("workflow") or
                                     name.endswith("model") for name in imported))
                self.assertFalse(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                                     for node in tree.body))

    def test_core_contracts_do_not_import_legacy_model_module(self):
        from apatch_lib.core import contracts
        tree = ast.parse(Path(contracts.__file__).read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and node.module == "model"
                             for node in tree.body))
        self.assertIs(contracts.RemoteOutcomeUnknown, publication.RemoteOutcomeUnknown)

    def test_models_have_no_io_and_parsing_is_separate(self):
        self.assertEqual(parsing.load_handoff.__module__, "apatch_lib.handoff.parsing")
        self.assertEqual(parsing.safe_relative.__module__, "apatch_lib.handoff.parsing")
        self.assertEqual(constants.HANDOFF_FIELDS,
                         frozenset({"schema_version", "repository", "feature_branch",
                                    "patch_file", "commit_message", "base_commit",
                                    "patch_sha256", "delete_paths"}))
        for module in (handoff_models, publication_models):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom)) and
                                 any(alias.name in {"os", "pathlib", "subprocess", "json", "shutil"}
                                     for alias in node.names) for node in tree.body))


if __name__ == "__main__":
    unittest.main()
