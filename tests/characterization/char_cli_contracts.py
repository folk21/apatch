"""Characterize stable public CLI inputs independently of implementation modules."""

import subprocess
import sys
import unittest

from tests._support import TOOL


class PublicCliContractTests(unittest.TestCase):
    """Preserve CLI spelling, safe validation, and documented action semantics."""

    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL / "apatch.py"), *args],
            cwd=TOOL,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )

    def test_help_exposes_all_numeric_and_mnemonic_lifecycle_actions(self) -> None:
        result = self._invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = result.stdout
        for operation in ("APL", "BRN", "CHK", "CMT", "PSH", "PR", "MRG", "SYN", "STS",
                          "AUD", "FMT", "REV"):
            with self.subTest(operation=operation):
                self.assertIn(operation, text)
        self.assertIn("--op", text)
        self.assertIn("--op-seq", text)
        self.assertIn("--followup", text)
        self.assertIn("--skip-approves", text)
        self.assertIn("--feature-branch", text)

    def test_bad_public_arguments_fail_before_any_repository_operation(self) -> None:
        for args in (("op=UNSUPPORTED",), ("skipApproves=maybe",),
                     ("--force", "--strict"), ("op=APL", "opSeq=APL,BRN")):
            with self.subTest(args=args):
                result = self._invoke(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("error:", result.stderr.lower())

    def test_help_is_readable_without_any_project_handoff(self) -> None:
        result = self._invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertIn("LOOSE", result.stdout)


if __name__ == "__main__":
    unittest.main()
