"""Black-box contracts for regular and extended test launchers."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]


class RunnerScriptsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for filename in ("run_tests.sh", "run_rare_checks.sh"):
            shutil.copy2(SOURCE_ROOT / filename, self.root / filename)
        self.interpreter = self.root / ".venv" / "bin" / "python"
        self.interpreter.parent.mkdir(parents=True)
        self.interpreter.write_text(
            '#!/bin/sh\n'
            'if [ "$1" = "-c" ]; then exit 0; fi\n'
            'printf "%s\\n" "$@" > "$APATCH_TEST_ARGV_FILE"\n',
            encoding="utf-8",
        )
        self.interpreter.chmod(0o755)
        self.arguments_file = self.root / "arguments.txt"

    def invoke(self, script, *options):
        environment = dict(os.environ, APATCH_TEST_ARGV_FILE=str(self.arguments_file))
        result = subprocess.run(
            ["sh", str(self.root / script), *options],
            capture_output=True, text=True, env=environment, check=False,
        )
        args = self.arguments_file.read_text().splitlines() if self.arguments_file.exists() else []
        return result, args

    def test_default_and_quick_run_regular_checks(self):
        for options in ((), ("regular",), ("quick",)):
            with self.subTest(options=options):
                result, args = self.invoke("run_tests.sh", *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(args[:4], ["-B", "-m", "unittest", "-v"])
                self.assertNotIn("discover", args)
                self.assertIn("tests.test_runner_scripts", args)
                self.assertIn("tests.test_handoffs.HandoffsTests.test_self_contained_lifecycle_strict", args)

    def test_rare_launcher_and_full_alias_run_all_tests(self):
        for script, options in (("run_rare_checks.sh", ()), ("run_tests.sh", ("full",))):
            with self.subTest(script=script):
                result, args = self.invoke(script, *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(args, ["-B", "-m", "unittest", "discover", "-s", "tests", "-v"])

    def test_invalid_mode_fails_without_launching_checks(self):
        result, args = self.invoke("run_tests.sh", "unknown")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)
        self.assertEqual(args, [])

    def test_github_workflow_has_no_automatic_triggers(self):
        workflow = (SOURCE_ROOT / ".github" / "workflows" / "tests.yml").read_text()
        self.assertRegex(workflow, r"(?m)^on:\s*\n  workflow_dispatch:\s*$")
        self.assertNotRegex(workflow, r"(?m)^  (push|pull_request):")
        self.assertIn("sh ./run_rare_checks.sh", workflow)
