"""Regression tests for validation contracts."""

from tests._support import (
    LocalGitFixture, command, TOOL, hashlib,
    json, os, re, shlex,
    shutil, stat, subprocess, sys,
    tempfile, unittest, zipfile, redirect_stdout,
    replace, datetime, StringIO, Path,
    patch, Abort, RemoteOutcomeUnknown, load_handoff,
    load_project_config, safe_relative, inspect, load_config,
    AppliedPatchHistory, ACTION_CODES, action_number, OperationSequence,
    execute_sequence, outcome_label,
)


class ValidationTest(unittest.TestCase):
    def test_every_action_code_maps_to_its_number(self):
        self.assertEqual(len(ACTION_CODES), 11)
        self.assertEqual(len(set(ACTION_CODES)), len(ACTION_CODES))
        for index, acronym in enumerate(ACTION_CODES):
            with self.subTest(action=acronym):
                self.assertGreaterEqual(len(acronym), 2)
                self.assertLessEqual(len(acronym), 4)
                self.assertTrue(acronym.isupper())
                self.assertEqual(action_number(acronym), index)
                self.assertEqual(action_number(acronym.lower()), index)
                self.assertEqual(action_number(str(index)), index)
        with self.assertRaises(ValueError):
            action_number("UNKNOWN")

    def test_relative_paths(self):
        for value in ["../foo", "x/../y", "x/.git/config", "/tmp/file", "x//y", "x\\y"]:
            with self.subTest(value=value), self.assertRaises(Abort):
                safe_relative(value)

    def test_command_line_logging_redacts_secret_arguments(self):
        from apatch_lib.gitutil import display_command
        rendered = display_command(["gh", "pr", "create", "--body", "confidential-body",
                                    "--token=secret-token", "--password", "secret-password"])
        self.assertIn("--body '[REDACTED]'", rendered)
        self.assertIn("'--token=[REDACTED]'", rendered)
        self.assertNotIn("confidential-body", rendered)
        self.assertNotIn("secret-token", rendered)
        self.assertNotIn("secret-password", rendered)

    def test_reject_paths_in_patch_basename(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "params.json"
            path.write_text(json.dumps({"schema_version": 1, "repository": "example_service",
                                        "feature_branch": "feature/test", "patch_file": "../patch.zip",
                                        "commit_message": "test: msg"}))
            with self.assertRaises(Abort):
                load_handoff(path)
