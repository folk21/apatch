"""Check that CLI help remains actionable across Python color conventions."""

import re
import subprocess
import sys
import unittest

from apatch_lib.cli_request import build_parser
from tests._support import TOOL


ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def plain_help(value: str) -> str:
    """Ignore presentation-only ANSI escapes introduced by newer argparse."""
    return ANSI_ESCAPE.sub("", value)


class HelpReferenceTests(unittest.TestCase):
    def test_plain_help_removes_only_ansi_presentation(self):
        self.assertEqual(plain_help("\x1b[1;36m--op\x1b[0m NUMBER|CODE"),
                         "--op NUMBER|CODE")

    def test_apatch_help_explains_workflows_configuration_and_recovery(self):
        help_text = plain_help(build_parser().format_help())
        for expected in (
            "ROOT OF THE TARGET GIT REPOSITORY",
            "schema_version: 1",
            "format_commands:",
            "prepare_checks:",
            "check_worktree_policy: stop",
            "dart", "cargo", "--set-exit-if-changed",
            "checks:", "check_idle_timeout_seconds:",
            "review_required: false", "reviewers:", "kind: llm", "kind: script",
            "skipApproves=true", "op=3", "op=APL", "opSeq=FMT,CHK,STS",
            "APPLY_PATCH_CHECK", "followup=true", "featureBranch=feature/new",
            "goal=MERGED", "info=PROGRESS", "verifyRemote=true",
            "preflight", "--op NUMBER|CODE", "LOOSE", "STRICT", "FORCE",
        ):
            with self.subTest(fragment=expected):
                self.assertIn(expected, help_text)

    def test_producer_help_explains_discovery_and_all_publishing_flags(self):
        result = subprocess.run([sys.executable, str(TOOL / "apatch_pack.py"), "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("--discover", "--include", "--delete", "--output", "--prepare",
                         "--base-commit", "--json", "format_commands", "READ-ONLY",
                         "source", "--message"):
            self.assertIn(expected, plain_help(result.stdout))

    def test_preflight_help_explains_mutation_and_read_only_checks(self):
        result = subprocess.run([sys.executable, str(TOOL / "apatch_preflight.py"),
                                 "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("--prepare", "--project", "--json", "format_commands",
                         "checks:", "READ-ONLY", "MUTATING", "--set-exit-if-changed"):
            self.assertIn(expected, plain_help(result.stdout))


if __name__ == "__main__":
    unittest.main()
