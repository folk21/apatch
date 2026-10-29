"""Black-box regression tests for explicit formatter execution."""

from tests._support import (LocalGitFixture, command, json, sys, unittest)


class FormattingTests(LocalGitFixture):
    def configure_formatting(self, *commands, timeout=30):
        config = ("schema_version: 1\n"
                  f"check_timeout_seconds: {timeout}\n"
                  "checks:\n  - [\"./run_checks.sh\"]\n"
                  "format_commands:\n")
        config += "".join("  - " + json.dumps(command) + "\n" for command in commands)
        self.configure_checks(config)

    def ready(self, *, mode="loose"):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip(f"--{mode}", "opSeq=APL,BRN", "skipApproves=true",
                                 selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_formatting_runs_before_read_only_checks_and_keeps_index(self):
        self.configure_formatting(
            [sys.executable, "-c", "from pathlib import Path; Path('existing.txt').write_text('formatted\\n')"])
        self.ready()
        before_index = command("git", "diff", "--cached", "--name-only", cwd=self.root).stdout
        result = self.invoke_zip("opSeq=FMT,CHK,STS", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("12 [FMT]", result.stdout)
        self.assertIn("4 [CHK]", result.stdout)
        self.assertIn("existing.txt", result.stdout)
        self.assertIn("canonical verification invalidated", result.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "formatted\n")
        self.assertEqual(command("git", "diff", "--cached", "--name-only",
                                 cwd=self.root).stdout, before_index)

    def test_direct_chk_does_not_run_format_commands(self):
        self.configure_formatting(
            [sys.executable, "-c", "from pathlib import Path; Path('fmt-marker').touch()"])
        self.ready()
        result = self.invoke_zip("op=CHK", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse((self.root / "fmt-marker").exists())

    def test_missing_format_configuration_and_prebranch_refused(self):
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        result = self.invoke_zip("op=FMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("format_commands", result.stderr)
        self.configure_formatting([sys.executable, "-c", "print('ready')"])
        result = self.invoke_zip("op=FMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("after BRN", result.stderr)

    def test_formatting_failure_preserves_edits_and_blocks_chk(self):
        self.configure_formatting([sys.executable, "-c",
                                   "from pathlib import Path; import sys; "
                                   "Path('existing.txt').write_text('kept\\n'); sys.exit(8)"])
        self.ready()
        result = self.invoke_zip("opSeq=FMT,CHK,STS", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("SEQUENCE STOP: 12 [FMT]", result.stdout)
        self.assertIn("Remaining (not executed): 4 [CHK]", result.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "kept\n")
        self.assertEqual(command("git", "branch", "--show-current",
                                 cwd=self.root).stdout.strip(), self.payload["feature_branch"])

    def test_formatting_timeout_blocks_sequence(self):
        self.configure_formatting([sys.executable, "-c", "import time; time.sleep(3)"],
                                  timeout=1)
        self.ready()
        result = self.invoke_zip("opSeq=FMT,CHK", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("timed out", result.stderr)
        self.assertNotIn("SEQUENCE ACTION 4 [CHK]", result.stdout)

    def test_index_mutation_is_reported_and_preserved(self):
        self.configure_formatting(["git", "add", "existing.txt"])
        self.ready()
        result = self.invoke_zip("op=12", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("FMT_INDEX_CHANGED", result.stderr)
        self.assertIn("existing.txt", result.stderr)
        self.assertIn("existing.txt", command("git", "diff", "--cached", "--name-only",
                                              cwd=self.root).stdout)

    def test_symlink_replacement_is_reported_and_preserved(self):
        self.configure_formatting([sys.executable, "-c",
                                   "from pathlib import Path; p=Path('existing.txt'); "
                                   "p.unlink(); p.symlink_to('new.txt')"])
        self.ready()
        result = self.invoke_zip("op=FMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("FMT_SYMLINK_CHANGED", result.stderr)
        self.assertTrue((self.root / "existing.txt").is_symlink())

    def test_previous_verified_snapshot_is_invalidated(self):
        self.configure_formatting([sys.executable, "-c",
                                   "from pathlib import Path; Path('existing.txt').write_text('formatted\\n')"])
        self.ready()
        checked = self.invoke_zip("op=CHK", "skipApproves=true")
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        formatted = self.invoke_zip("op=FMT", "skipApproves=true")
        self.assertEqual(formatted.returncode, 0, formatted.stderr + formatted.stdout)
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["phase"], "patch_applied")
        self.assertNotIn("verified_fingerprint", record)
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)

    def test_strict_accepts_explicit_formatting_after_brn(self):
        self.configure_formatting([sys.executable, "-c", "print('FORMAT COMPLETE')"])
        self.ready(mode="strict")
        result = self.invoke_zip("--strict", "opSeq=FMT,CHK", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("FORMAT COMPLETE", result.stdout)

    def test_force_accepts_explicit_formatting_after_brn(self):
        self.configure_formatting([sys.executable, "-c", "print('FORMAT COMPLETE')"])
        self.ready(mode="force")
        result = self.invoke_zip("--force", "opSeq=FMT,CHK", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("FORMAT COMPLETE", result.stdout)

    def test_new_untracked_formatter_output_is_preserved_and_reported(self):
        self.configure_formatting([sys.executable, "-c",
                                   "from pathlib import Path; Path('generated.txt').write_text('new\\n')"])
        self.ready()
        result = self.invoke_zip("op=FMT", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("generated.txt", result.stdout)
        self.assertEqual((self.root / "generated.txt").read_text(), "new\n")
        self.assertIn("?? generated.txt", command("git", "status", "--porcelain",
                                                   cwd=self.root).stdout)

    def test_executable_bit_change_is_reported(self):
        self.configure_formatting([sys.executable, "-c",
                                   "from pathlib import Path; import os; "
                                   "os.chmod('existing.txt', 0o755)"])
        self.ready()
        result = self.invoke_zip("op=FMT", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("existing.txt", result.stdout)
        self.assertIn("executable", result.stdout)

    def test_formatter_drift_of_project_policy_blocks_remaining_commands(self):
        self.configure_formatting(
            [sys.executable, "-c", "from pathlib import Path; "
             "p=Path('.apatch/config.yaml'); p.write_text(p.read_text() + '# changed\\n')"],
            [sys.executable, "-c", "from pathlib import Path; Path('unexpected.txt').touch()"])
        self.ready()
        result = self.invoke_zip("op=FMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("FMT_CONFIG_DRIFT", result.stderr)
        self.assertNotIn("FORMAT 2/2", result.stdout)
        self.assertFalse((self.root / "unexpected.txt").exists())


if __name__ == "__main__":
    unittest.main()
