"""Black-box checks for optional build execution and verification isolation."""

from tests._support import LocalGitFixture, command, json, sys, unittest


class BuildActionTests(LocalGitFixture):
    def configure_build(self, *commands, timeout=30):
        config = ("schema_version: 1\n"
                  f"check_timeout_seconds: {timeout}\n"
                  "checks:\n  - [\"./run_checks.sh\"]\n"
                  "build_commands:\n")
        config += "".join("  - " + json.dumps(command) + "\n" for command in commands)
        self.configure_checks(config)

    def ready(self, *, mode="loose"):
        selected = self.make_self_contained_zip()
        result = self.invoke_zip(f"--{mode}", "opSeq=APL,BRN", "skipApproves=true",
                                 selection=selected)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def workflow_record(self):
        state = json.loads(self.state_path.read_text())
        return next(iter(state["workflows"].values()))

    def test_build_only_runs_build_and_does_not_verify(self):
        self.configure_build([sys.executable, "-c", "print('BUILD ONLY')"])
        self.ready()
        result = self.invoke_zip("op=BLD", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("14 [BLD]", result.stdout)
        self.assertIn("BUILD ONLY", result.stdout)
        self.assertNotIn("CANONICAL CHECK PASS", result.stdout)
        self.assertEqual(self.workflow_record()["phase"], "patch_applied")
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["operation_runs"][-1]["operation"],
                         {"number": 14, "code": "BLD"})
        self.assertEqual(state["operation_runs"][-1]["outcome"], "SUCCEEDED")

    def test_build_followed_by_chk_checks_and_commit_gate(self):
        self.configure_build([sys.executable, "-c", "print('BUILD SUCCESS')"])
        self.ready()
        result = self.invoke_zip("opSeq=BLD,CHK,STS", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("SEQUENCE ACTION 14 [BLD]", result.stdout)
        self.assertIn("SEQUENCE ACTION 4 [CHK]", result.stdout)
        self.assertEqual(self.workflow_record()["phase"], "verified")

    def test_missing_configuration_and_pre_branch_refuse(self):
        self.ready()
        result = self.invoke_zip("op=14", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("build_commands", result.stderr)

    def test_uncommitted_main_refused(self):
        self.configure_build([sys.executable, "-c", "print('MUST NOT RUN')"])
        selected = self.make_self_contained_zip()
        self.assertEqual(self.invoke_zip("op=APL", "skipApproves=true",
                                         selection=selected).returncode, 0)
        result = self.invoke_zip("op=BLD", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("MUST NOT RUN", result.stdout)

    def test_failed_build_preserves_output_and_blocks_following_chk(self):
        self.configure_build([sys.executable, "-c", "import sys; sys.exit(7)"])
        self.ready()
        result = self.invoke_zip("opSeq=BLD,CHK,STS", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("SEQUENCE STOP: 14 [BLD]", result.stdout)
        self.assertNotIn("SEQUENCE ACTION 4 [CHK]", result.stdout)
        self.assertEqual(self.workflow_record()["phase"], "patch_applied")

    def test_build_invalidates_previous_chk_even_after_failure(self):
        self.configure_build([sys.executable, "-c", "import sys; sys.exit(7)"])
        self.ready()
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        result = self.invoke_zip("op=BLD", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.workflow_record()["phase"], "patch_applied")
        self.assertNotIn("verified_fingerprint", self.workflow_record())

    def test_build_changed_tracked_file_is_preserved_and_rejected(self):
        self.configure_build([sys.executable, "-c",
                              "from pathlib import Path; Path('existing.txt').write_text('new-build' + chr(10))"])
        self.ready()
        result = self.invoke_zip("op=BLD", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLD_WORKTREE_CHANGED", result.stderr)
        self.assertEqual((self.root / "existing.txt").read_text(), "new-build\n")

    def test_build_changed_index_is_preserved_and_rejected(self):
        self.configure_build(["git", "add", "existing.txt"])
        self.ready()
        result = self.invoke_zip("op=BLD", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLD_INDEX_CHANGED", result.stderr)
        self.assertIn("existing.txt", command("git", "diff", "--cached", "--name-only",
                                               cwd=self.root).stdout)

    def test_build_timeout_blocks_sequence(self):
        self.configure_build([sys.executable, "-c", "import time; time.sleep(3)"], timeout=1)
        self.ready()
        result = self.invoke_zip("opSeq=BLD,CHK", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("timed out", result.stderr)
        self.assertNotIn("SEQUENCE ACTION 4 [CHK]", result.stdout)

    def test_strict_build_uses_separate_action(self):
        self._verify_mode("strict")

    def test_force_build_uses_separate_action(self):
        self._verify_mode("force")

    def _verify_mode(self, mode):
        self.configure_build([sys.executable, "-c", "print('BUILD IN MODE')"])
        self.ready(mode=mode)
        result = self.invoke_zip(f"--{mode}", "op=BLD", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("BUILD IN MODE", result.stdout)

    def test_completed_publication_replay_patterns_include_build(self):
        from apatch_lib.sequence import COMPLETED_PUBLICATION_REPLAYS

        self.assertIn((3, 1, 14, 4, 5, 6, 7, 8, 9, 10),
                      COMPLETED_PUBLICATION_REPLAYS)
        self.assertIn((3, 1, 12, 14, 4, 13, 5, 6, 7, 8, 9, 10),
                      COMPLETED_PUBLICATION_REPLAYS)

    def test_invalid_build_config_is_rejected_before_execution(self):
        invalid_values = ("null", "true", "[123]", "[[\"python3 -c hi\"]]",
                          "[[]]", "[[\"python3\", null]]")
        for value in invalid_values:
            with self.subTest(value=value):
                self.configure_checks('schema_version: 1\nchecks:\n  - ["./run_checks.sh"]\n'
                                      f'build_commands: {value}\n')
                result = self.invoke_cli("op=STS")
                if value == '[["python3 -c hi"]]':
                    self.assertEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("build_commands", result.stderr)
