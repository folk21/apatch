"""R2 configuration ownership and historical import compatibility."""

import ast
import dataclasses
import tempfile
import unittest
from pathlib import Path

from apatch_lib import model
from apatch_lib.configuration import api as config_api
from apatch_lib.configuration import loaders, models, validators
from apatch_lib.core.errors import Abort
from apatch_lib.review import api as review_api


class ConfigurationArchitectureTests(unittest.TestCase):
    def test_historical_public_identifiers_are_identity_aliases(self) -> None:
        for historical, canonical in (
            (model.Abort, Abort),
            (model.Config, config_api.Config),
            (model.ReviewProvider, review_api.ReviewProvider),
            (model.ScannerPolicy, review_api.ScannerPolicy),
            (model.load_config, config_api.load_config),
            (model.load_project_config, config_api.load_project_config),
            (model.validate_base_branch, config_api.validate_base_branch),
            (model.validate_log_subdirectory, config_api.validate_log_subdirectory),
            (model.validate_runtime_filename, config_api.validate_runtime_filename),
        ):
            with self.subTest(historical=historical):
                self.assertIs(historical, canonical)

    def test_models_are_immutable_and_have_domain_owners(self) -> None:
        self.assertEqual(models.Config.__module__, "apatch_lib.configuration.models")
        self.assertEqual(review_api.ReviewProvider.__module__, "apatch_lib.review.models")
        self.assertEqual(review_api.ScannerPolicy.__module__, "apatch_lib.review.models")
        for cls in (models.Config, review_api.ReviewProvider, review_api.ScannerPolicy):
            self.assertTrue(dataclasses.is_dataclass(cls))
            self.assertTrue(cls.__dataclass_params__.frozen)

    def test_model_source_only_contains_models_and_handoff_parsing(self) -> None:
        tree = ast.parse(Path(model.__file__).read_text(encoding="utf-8"))
        names = {node.name for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        self.assertFalse({"Config", "load_config", "load_project_config",
                          "ReviewProvider", "ScannerPolicy"} & names)
        for component in (models, review_api):
            tree = ast.parse(Path(component.__file__).read_text(encoding="utf-8"))
            self.assertFalse(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                                 for node in tree.body))

    def test_global_and_project_loaders_return_identical_effective_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installation = root / "installation"
            installation.mkdir()
            (installation / "apatch.conf").write_text(
                "[apatch]\nbase_branch = main\nremote = origin\n"
                "github_timeout_seconds = 30\n", encoding="utf-8")
            project = root / "sample"
            (project / ".apatch").mkdir(parents=True)
            (project / ".apatch" / "config.yaml").write_text(
                'schema_version: 1\nchecks:\n  - ["python3", "-B", "-m", "unittest"]\n'
                'base_branch: develop\nreview_retention_max_runs: 7\n', encoding="utf-8")
            global_config = config_api.load_config(installation)
            actual = loaders.load_project_config(project, global_config)
            self.assertEqual(actual, model.load_project_config(project, global_config))
            self.assertIs(type(actual), models.Config)
            self.assertEqual(actual.base, "develop")
            self.assertEqual(actual.base_branch_source, "project")
            self.assertEqual(actual.checks, (("python3", "-B", "-m", "unittest"),))
            self.assertEqual(actual.review_retention_max_runs, 7)

    def test_invalid_settings_rejected_without_creating_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installation = root / "installation"
            installation.mkdir()
            (installation / "apatch.conf").write_text(
                "[apatch]\nbase_branch = main\n", encoding="utf-8")
            project = root / "sample"
            (project / ".apatch").mkdir(parents=True)
            config_path = project / ".apatch" / "config.yaml"
            global_config = config_api.load_config(installation)
            for invalid, message in (
                ('schema_version: 1\nchecks: []\n', 'non-empty list'),
                ('schema_version: 1\nchecks: ["echo"]\n'
                 'check_timeout_seconds: 0\n', 'check_timeout_seconds'),
                ('schema_version: 1\nchecks: ["echo"]\n'
                 'review_retention_max_runs: 0\n', 'review_retention_max_runs'),
                ('schema_version: 1\nchecks: ["echo"]\n'
                 'review_required: true\n', 'requires at least one'),
            ):
                with self.subTest(invalid=invalid):
                    config_path.write_text(invalid, encoding="utf-8")
                    with self.assertRaisesRegex(Abort, message):
                        config_api.load_project_config(project, global_config)
                    self.assertFalse((project / ".apatch" / "apply_patch.state.json").exists())

    def test_symlinked_project_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installation = root / "installation"
            installation.mkdir()
            (installation / "apatch.conf").write_text(
                "[apatch]\nbase_branch = main\n", encoding="utf-8")
            project = root / "sample"
            (project / ".apatch").mkdir(parents=True)
            other = root / "external.yaml"
            other.write_text('schema_version: 1\nchecks: ["echo ok"]\n',
                             encoding="utf-8")
            (project / ".apatch" / "config.yaml").symlink_to(other)
            with self.assertRaisesRegex(Abort, 'must not be a symlink'):
                config_api.load_project_config(project, config_api.load_config(installation))

    def test_validators_keep_original_branch_and_path_errors(self) -> None:
        for invalid in ("release//broken", "-flag", "topic.lock", "branch..suffix"):
            with self.subTest(value=invalid):
                with self.assertRaises(Abort):
                    validators.validate_base_branch(invalid, source="project")
        with self.assertRaises(Abort):
            validators.validate_log_subdirectory("../escape")
        with self.assertRaises(Abort):
            validators.validate_runtime_filename("config.yaml")


if __name__ == "__main__":
    unittest.main()
