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
            "REUSE AN UNCHANGED ZIP WITH A DIFFERENT FEATURE BRANCH",
            "featureBranch=feature/new-work", "featureBranch=feature/current-work",
            "opSeq=APL,BRN,CHK,STS", "followup=true opSeq=APL,FMT,CHK,STS",
            "existing feature branch", "original", "ZIP", "archive hash",
            "ALREADY_COMPLETED", "dirty base, or changed remote",
            "goal=MERGED", "info=PROGRESS", "verifyRemote=true",
            "preflight", "--op NUMBER|CODE", "LOOSE", "STRICT", "FORCE",
        ):
            with self.subTest(fragment=expected):
                self.assertIn(expected, help_text)

    def test_usage_guide_covers_supported_workflows_and_recovery(self):
        guide = (TOOL / "docs" / "USAGE.md").read_text(encoding="utf-8")
        for expected in (
            "## 1. Prepare a target repository",
            "## 2. Understand the handoff ZIP",
            "## 3. First ZIP: APL before BRN",
            "## 4. Continue a feature with another ZIP",
            "## 5. Modes, actions and operation sequences",
            "## 6. Checks, formatting, builds and review",
            "## 7. Publication, PRs and synchronization",
            "## 8. Guarded goals and named macros",
            "## 9. Produce a ZIP from source",
            "## 10. Diagnose, recover and resume safely",
            "## 11. Security, privacy and compatibility",
            "opSeq=APL,BRN,CHK,STS", "followup=true", "handoffSeq=",
            "disabledWithoutChk=MRG", "CHECK_GATE_MRG", "delete_paths",
            "review_context_external_consent", "skipApproves=true",
        ):
            with self.subTest(fragment=expected):
                self.assertIn(expected, guide)
        self.assertIn("not** CLI features yet", guide)

    def test_producer_help_explains_discovery_and_all_publishing_flags(self):
        result = subprocess.run([sys.executable, str(TOOL / "scripts" / "apatch_pack.py"), "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("--discover", "--include", "--delete", "--output", "--prepare",
                         "--base-commit", "--json", "format_commands", "READ-ONLY",
                         "source", "--message"):
            self.assertIn(expected, plain_help(result.stdout))

    def test_preflight_help_explains_mutation_and_read_only_checks(self):
        result = subprocess.run([sys.executable, str(TOOL / "scripts" / "apatch_preflight.py"),
                                 "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("--prepare", "--project", "--json", "format_commands",
                         "checks:", "READ-ONLY", "MUTATING", "--set-exit-if-changed"):
            self.assertIn(expected, plain_help(result.stdout))


if __name__ == "__main__":
    unittest.main()