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
        for filename in ("run_tests.sh", "run_rare_checks.sh", "run_quality.sh"):
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
                self.assertEqual(args[:4], ["-B", "-m", "tests.timeout_runner", "-v"])
                self.assertNotIn("discover", args)
                self.assertIn("tests.test_runner_scripts", args)
                self.assertIn("tests.test_context", args)
                self.assertIn("tests.test_session_continuation", args)
                self.assertIn("tests.test_handoffs.HandoffsTests.test_self_contained_lifecycle_strict", args)

    def test_rare_launcher_and_full_alias_run_all_tests(self):
        for script, options in (("run_rare_checks.sh", ()), ("run_tests.sh", ("full",))):
            with self.subTest(script=script):
                result, args = self.invoke(script, *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(args, ["-B", "-m", "tests.timeout_runner", "--full"])

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

    def prepare_quality_interpreter(self):
        """Capture module commands and optionally simulate missing quality tools."""
        self.interpreter.write_text(
            '#!/bin/sh\n'
            'if [ "$1" = "-B" ]; then shift; fi\n'
            'if [ "$1" = "-m" ] && [ "$3" = "--version" ]; then\n'
            '    if [ "${APATCH_TEST_MISSING_MODULE:-}" = "$2" ]; then exit 1; fi\n'
            '    exit 0\n'
            'fi\n'
            'printf "%s\\n" "COMMAND" "$@" >> "$APATCH_TEST_ARGV_FILE"\n',
            encoding="utf-8",
        )
        self.interpreter.chmod(0o755)

    def test_quality_gate_scopes_checks_without_reformatting(self):
        self.prepare_quality_interpreter()
        result, arguments = self.invoke("run_quality.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = "\n".join(arguments).split("COMMAND\n")[1:]
        self.assertEqual(len(commands), 3)
        lint, formatting, types = (command.splitlines() for command in commands)
        self.assertEqual(lint[:3], ["-m", "ruff", "check"])
        self.assertIn("--no-cache", lint)
        self.assertIn("apatch_lib/audit_rules.py", lint)
        self.assertEqual(formatting[:3], ["-m", "ruff", "format"])
        self.assertIn("--check", formatting)
        self.assertIn("--no-cache", formatting)
        self.assertNotIn("--fix", formatting)
        self.assertEqual(types[:3], ["-m", "mypy", "--no-incremental"])
        self.assertIn("--cache-dir=/dev/null", types)
        self.assertNotIn("--install-types", types)

    def test_quality_gate_reports_missing_optional_dependency_as_not_run(self):
        self.prepare_quality_interpreter()
        for mode, missing in (("lint", "ruff"), ("types", "mypy"), ("all", "mypy")):
            with self.subTest(mode=mode, missing=missing):
                self.arguments_file.unlink(missing_ok=True)
                environment = dict(os.environ, APATCH_TEST_ARGV_FILE=str(self.arguments_file),
                                   APATCH_TEST_MISSING_MODULE=missing)
                result = subprocess.run(
                    ["sh", str(self.root / "run_quality.sh"), mode],
                    capture_output=True, text=True, env=environment, check=False,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(f"NOT_RUN: {'Ruff' if missing == 'ruff' else 'mypy'}", result.stderr)

    def test_quality_gate_rejects_unknown_mode_before_launching(self):
        self.prepare_quality_interpreter()
        result, arguments = self.invoke("run_quality.sh", "unsupported")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)
        self.assertEqual(arguments, [])
