"""Producer-side preflight tests using only local temporary Git repositories."""

import json
import shutil
import subprocess
import sys

from apatch_lib.artifact_preflight import preflight
from apatch_lib.model import Abort

from tests._support import TOOL, LocalGitFixture


class ArtifactPreflightTests(LocalGitFixture):
    def setUp(self):
        super().setUp()
        (self.root / "new.txt").write_text("new\n")

    def run_preflight(self, *, prepare=False):
        return preflight(self.root, self.bin, prepare=prepare)

    def configure_checks(self, *, checks=None, formatting=None):
        checks = checks or ['./run_checks.sh']
        value = 'schema_version: 1\ncheck_timeout_seconds: 5\ncheck_idle_timeout_seconds: 5\n'
        value += 'checks:\n'
        for command in checks:
            value += f'  - ["{command}"]\n'
        if formatting is not None:
            value += 'format_commands:\n'
            for command in formatting:
                value += f'  - ["{command}"]\n'
        self.project_config.write_text(value)

    def test_read_only_preflight_captures_exact_source_evidence(self):
        result = self.run_preflight()
        self.assertEqual(result.repository, "example_service")
        self.assertEqual(result.branch, "main")
        self.assertEqual(result.head, self.head)
        self.assertFalse(result.prepared)
        self.assertIn("new.txt", result.changed_paths)
        self.assertEqual(len(result.worktree_sha256), 64)
        self.assertEqual(result.check_commands_run, 1)
        self.assertEqual(result.to_dict()["status"], "passed")

    def test_preparation_runs_only_when_explicitly_requested(self):
        formatter = self.root / "format.sh"
        formatter.write_text("#!/bin/sh\nset -eu\nprintf 'formatted\\n' > new.txt\n")
        formatter.chmod(0o755)
        self.configure_checks(formatting=["./format.sh"])
        first = self.run_preflight()
        self.assertFalse(first.prepared)
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")
        second = self.run_preflight(prepare=True)
        self.assertTrue(second.prepared)
        self.assertEqual(second.format_commands_run, 1)
        self.assertEqual((self.root / "new.txt").read_text(), "formatted\n")

    def test_preparation_without_format_commands_fails_without_mutation(self):
        with self.assertRaisesRegex(Abort, "requires project format_commands"):
            self.run_preflight(prepare=True)
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")

    def test_preparation_must_not_stage_files(self):
        script = self.root / "format.sh"
        script.write_text("#!/bin/sh\nset -eu\ngit add new.txt\n")
        script.chmod(0o755)
        self.configure_checks(formatting=["./format.sh"])
        with self.assertRaisesRegex(Abort, "modified the Git index"):
            self.run_preflight(prepare=True)

    def test_canonical_check_that_changes_source_is_rejected(self):
        runner = self.root / "run_checks.sh"
        runner.write_text("#!/bin/sh\nset -eu\nprintf 'changed\\n' > new.txt\n")
        with self.assertRaisesRegex(Abort, "Read-only verification changed.*new.txt"):
            self.run_preflight()

    def test_canonical_check_failure_identifies_command(self):
        runner = self.root / "run_checks.sh"
        runner.write_text("#!/bin/sh\nexit 7\n")
        with self.assertRaisesRegex(Abort, "CHECK 1/1 failed.*Command failed \\(7\\)"):
            self.run_preflight()

    def test_missing_check_executable_fails_closed(self):
        self.configure_checks(checks=["./missing-check-command"])
        with self.assertRaisesRegex(Abort, "CHECK 1/1 failed: Cannot execute"):
            self.run_preflight()

    def test_whitespace_error_fails_before_canonical_check(self):
        (self.root / "existing.txt").write_text("trailing  \n")
        with self.assertRaisesRegex(Abort, "git diff --check"):
            self.run_preflight()

    def test_read_only_check_cannot_switch_branch(self):
        runner = self.root / "run_checks.sh"
        runner.write_text("#!/bin/sh\nset -eu\ngit switch -c feature/unexpected\n")
        with self.assertRaisesRegex(Abort, "changed the Git branch or HEAD"):
            self.run_preflight()

    def test_timeout_fails_without_marking_source_as_verified(self):
        runner = self.root / "run_checks.sh"
        runner.write_text("#!/bin/sh\nset -eu\nsleep 4\n")
        self.project_config.write_text(
            self.project_config.read_text().replace("check_timeout_seconds: 30",
                                                    "check_timeout_seconds: 1"))
        with self.assertRaisesRegex(Abort, "CHECK 1/1 failed.*timed out"):
            self.run_preflight()

    def test_json_output_is_machine_readable_on_success_and_failure(self):
        shutil.copy(TOOL / "apatch_preflight.py", self.bin / "apatch_preflight.py")
        command = [sys.executable, str(self.bin / "apatch_preflight.py"),
                   "--project", str(self.root), "--json"]
        good = subprocess.run(command, cwd=self.root, capture_output=True,
                              text=True, timeout=15)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)["status"], "passed")
        self.assertIn("PREFLIGHT CHECK", good.stderr)

        self.configure_checks(checks=["./missing-check-command"])
        bad = subprocess.run(command, cwd=self.root, capture_output=True,
                             text=True, timeout=15)
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(json.loads(bad.stdout)["status"], "failed")
        self.assertIn("missing-check-command", bad.stderr)


if __name__ == "__main__":
    import unittest
    unittest.main()
