"""Regression tests for the config cli subsystem."""

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


class ConfigCliTests(LocalGitFixture):
    def test_project_config_is_required(self):
        self.project_config.unlink()
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing project checks config", result.stderr)

    def test_empty_and_invalid_project_checks_are_rejected(self):
        cases = [
            ("schema_version: 1\nchecks: []\n", "non-empty list"),
            ("schema_version: 1\nchecks: [42]\n", "command string or argv list"),
            ("schema_version: 1\nchecks:\n  - []\n", "invalid arguments"),
            ("schema_version: 2\nchecks:\n  - echo ok\n", "schema_version"),
            ("checks: [echo ok]\n", "schema_version and checks"),
            ("schema_version: [\n", "Invalid project checks YAML"),
        ]
        for yaml_text, reason in cases:
            with self.subTest(yaml_text=yaml_text):
                self.project_config.write_text(yaml_text)
                result = self.invoke("0\n")
                self.assertEqual(result.returncode, 2)
                self.assertIn(reason, result.stderr)

    def test_project_config_parses_multiple_commands(self):
        self.project_config.write_text(
            'schema_version: 1\nlog_directory: build/checks\nchecks:\n'
            '  - ./gradlew test\n  - ["python3", "-c", "print(42)"]\n')
        config = load_project_config(self.root, load_config(self.bin))
        self.assertEqual(config.checks, (("./gradlew", "test"), ("python3", "-c", "print(42)")))
        self.assertEqual(config.log_directory, self.root / ".apatch" / "build" / "checks")

    def test_project_review_approval_inherits_global_setting_when_omitted(self):
        global_config = load_config(self.bin)
        self.assertTrue(global_config.require_approval)
        for required in (True, False):
            with self.subTest(global_required=required):
                config = load_project_config(self.root, replace(global_config, require_approval=required))
                self.assertIs(config.require_approval, required)
                self.assertEqual(config.review_approval_source, "global")

    def test_project_review_approval_overrides_global_setting(self):
        global_config = load_config(self.bin)
        for required in (True, False):
            with self.subTest(project_required=required):
                self.project_config.write_text(
                    "schema_version: 1\nchecks:\n  - [\"./run_checks.sh\"]\n"
                    f"require_review_approval: {str(required).lower()}\n")
                config = load_project_config(self.root, replace(global_config, require_approval=not required))
                self.assertIs(config.require_approval, required)
                self.assertEqual(config.review_approval_source, "project")

    def test_project_review_approval_rejects_non_boolean_values(self):
        for value in ('"false"', "0", "1", "null", "[]", "{}"):
            with self.subTest(value=value):
                self.project_config.write_text(
                    f"schema_version: 1\nchecks:\n  - [\"./run_checks.sh\"]\n"
                    f"require_review_approval: {value}\n")
                result = self.invoke_cli("op=EXT")
                self.assertEqual(result.returncode, 2)
                self.assertIn("require_review_approval must be a YAML boolean", result.stderr)

    def test_project_ci_policy_inherits_global_setting_when_omitted(self):
        global_config = load_config(self.bin)
        for required in (True, False):
            with self.subTest(global_required=required):
                config = load_project_config(self.root, replace(global_config, require_checks=required))
                self.assertIs(config.require_checks, required)
                self.assertEqual(config.required_checks_source, "global")

    def test_project_ci_policy_overrides_global_setting_independently(self):
        global_config = load_config(self.bin)
        for required in (True, False):
            with self.subTest(project_required=required):
                self.project_config.write_text(
                    "schema_version: 1\nchecks:\n  - [\"./run_checks.sh\"]\n"
                    "require_review_approval: true\n"
                    f"require_required_checks: {str(required).lower()}\n")
                config = load_project_config(self.root, replace(global_config, require_checks=not required))
                self.assertIs(config.require_checks, required)
                self.assertEqual(config.required_checks_source, "project")
                self.assertTrue(config.require_approval)

    def test_project_ci_policy_rejects_non_boolean_values(self):
        for value in ('"false"', "0", "1", "null", "[]", "{}"):
            with self.subTest(value=value):
                self.project_config.write_text(
                    f"schema_version: 1\nchecks:\n  - [\"./run_checks.sh\"]\n"
                    f"require_required_checks: {value}\n")
                result = self.invoke_cli("op=EXT")
                self.assertEqual(result.returncode, 2)
                self.assertIn("require_required_checks must be a YAML boolean", result.stderr)

    def test_project_config_can_run_a_nonstandard_check_script(self):
        script = self.root / "custom_verify.sh"
        script.write_text("#!/bin/sh\nset -eu\ntest -f new.txt\n")
        script.chmod(0o755)
        self.configure_checks('schema_version: 1\nchecks:\n  - ["./custom_verify.sh"]\n')
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        result = self.invoke("4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log_path.read_text()
        self.assertIn("./custom_verify.sh", log)
        self.assertNotIn("./run_checks.sh", log)

    def test_successful_project_check_output_is_visible_but_not_logged(self):
        script = self.root / "custom_verify.sh"
        script.write_text("#!/bin/sh\nset -eu\nprintf 'CHECK STDOUT\\n'\n"
                          "printf 'CHECK STDERR\\n' >&2\ntest -f new.txt\n")
        script.chmod(0o755)
        self.configure_checks('schema_version: 1\nchecks:\n  - ["./custom_verify.sh"]\n')
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        result = self.invoke("4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CHECK STDOUT", result.stdout)
        self.assertIn("CHECK STDERR", result.stdout)
        log = self.log_path.read_text()
        self.assertIn("command start", log)
        self.assertIn("argv=./custom_verify.sh", log)
        self.assertNotIn("CHECK STDOUT", log)
        self.assertNotIn("CHECK STDERR", log)
        self.assertNotIn("check command failed", log)
        check_events = [line for line in log.splitlines() if "argv=./custom_verify.sh" in line]
        self.assertEqual(len(check_events), 1)
        self.assertIn("command start", check_events[0])
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         " M existing.txt\n?? new.txt\n")

    def test_menu_lists_every_action_even_when_git_state_blocks_actions(self):
        (self.root / "untracked.txt").write_text("dirty\n")
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"\n-----\nRepository: {self.root.resolve()}\n"
                      f"Feature branch: {self.payload['feature_branch']}\n"
                      f"Patch: {self.zip.name}\nPhase: new\n"
                      "Current branch: main\nMode: STRICT", result.stdout)
        expected_labels = [
            "Create a feature branch",
            "Create a feature branch and apply patch",
            "Apply patch to current branch (main)",
            "Run/re-run canonical checks",
            "Commit and push all verified changes",
            "Retry push of the existing commit",
            "Create/find PR",
            "Merge PR into",
            "Resume synchronization of local",
        ]
        for index, label in enumerate(expected_labels, start=1):
            self.assertIn(f" {index}. [{ACTION_CODES[index]}] {label}", result.stdout)
        self.assertIn(" 0. [EXT] Exit", result.stdout)
        self.assertIn("requires a clean working tree", result.stdout)

    def test_unavailable_action_reports_reason_without_mutating_git(self):
        (self.root / "untracked.txt").write_text("dirty\n")
        result = self.invoke("1\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Action unavailable: requires a clean working tree", result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        self.assertFalse((self.root / "new.txt").exists())

    def test_force_menu_exposes_all_actions_without_phase_blockers(self):
        (self.root / "untracked.txt").write_text("uncommitted\n")
        result = self.invoke_force("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mode: FORCE (manual recovery)", result.stdout)
        self.assertIn(" 1. [BRN] Create/adopt a feature branch\n", result.stdout)
        self.assertIn(" 9. [SYN] Synchronize local main and reconcile PR status\n", result.stdout)
        self.assertNotIn("requires phase:", result.stdout)

    def test_loose_menu_and_mutually_exclusive_modes(self):
        (self.root / "manual.txt").write_text("manual\n")
        result = self.invoke_loose("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mode: LOOSE", result.stdout)
        self.assertIn(" 3. [APL] Apply another patch to current branch (main)\n", result.stdout)
        self.assertIn(" 5. [CMT] Commit accumulated changes (do not push)\n", result.stdout)
        self.assertIn(" 6. [PSH] Push committed changes on current branch\n", result.stdout)
        self.assertNotIn("requires phase:", result.stdout)
        rejected = self.invoke("0\n", "--loose", "--force")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("not allowed with argument", rejected.stderr)

    def test_default_mode_is_loose_and_help_documents_all_modes_and_automation(self):
        result = self.invoke_cli(text="0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mode: LOOSE (default", result.stdout)
        self.assertIn("Available modes: LOOSE (default), STRICT, FORCE", result.stdout)
        self.assertIn(" 5. [CMT] Commit accumulated changes (do not push)", result.stdout)
        help_result = subprocess.run([sys.executable, str(self.bin / "apatch.py"), "--help"],
                                     cwd=self.root, capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        plain_help = re.sub(r"\x1b\[[0-9;]*m", "", help_result.stdout)
        for fragment in ("LOOSE (default)", "STRICT", "FORCE", "op=3", "op=APL",
                         "skipApproves=true", "default: false", "--op NUMBER|CODE"):
            self.assertIn(fragment, plain_help)

    def test_mnemonic_direct_actions_and_verbose_result_summary(self):
        applied = self.invoke_cli("op=APL", "skipApproves=true")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Selected action via op=APL (#3, APL)", applied.stdout)
        self.assertIn("==> START 3 [APL]", applied.stdout)
        self.assertIn("==> RESULT 3 [APL]", applied.stdout)
        self.assertIn("Phase: new -> patch_applied", applied.stdout)
        self.assertIn("Working-tree changes: 0 -> 2 path(s)", applied.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")
        checked = self.invoke_cli("--op=chk", "skipApproves=true")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("Selected action via op=CHK", checked.stdout)
        self.assertIn("[OK] Project check completed", checked.stdout)
        self.assertIn("Phase: patch_applied -> verified", checked.stdout)
        committed = self.invoke_cli("op=CMT", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertIn("[OK] Git staging completed", committed.stdout)
        self.assertIn("[OK] Git commit completed", committed.stdout)
        self.assertIn("Phase: verified -> committed", committed.stdout)
        self.assertIn("Working-tree changes: 2 -> 0 path(s)", committed.stdout)
        pushed = self.invoke_cli("op=PSH", "skipApproves=true")
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        self.assertIn("[OK] Git push completed", pushed.stdout)
        self.assertIn("Phase: committed -> pushed", pushed.stdout)

    def test_mnemonic_interactive_selection_and_exit(self):
        exited = self.invoke_cli("op=EXT")
        self.assertEqual(exited.returncode, 0, exited.stderr)
        self.assertIn("Exit selected. No action was run.", exited.stdout)
        applied = self.invoke_loose("APL\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("==> START 3 [APL]", applied.stdout)
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")

    def test_direct_action_without_approvals_applies_checks_commits_and_pushes(self):
        applied = self.invoke_cli("op=3", "skipApproves=true")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Selected action via op=3", applied.stdout)
        self.assertIn("auto-approved: skipApproves=true", applied.stdout)
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")
        self.assert_history(real_branch="main")
        checked = self.invoke_cli("--op=4", "--skip-approves=true")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("Canonical checks passed", checked.stdout)
        committed = self.invoke_cli("op=5", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertIn("Push remains a separate action", committed.stdout)
        sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.assertNotEqual(sha, self.head)
        remote_sha_before = command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                                    cwd=self.root).stdout.split()[0]
        self.assertEqual(remote_sha_before, self.head)
        pushed = self.invoke_cli("op=6", "skipApproves=true")
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        self.assertIn("Push reconciled", pushed.stdout)
        remote_sha_after = command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                                   cwd=self.root).stdout.split()[0]
        self.assertEqual(remote_sha_after, sha)
        self.assertEqual(next(iter(json.loads(self.state_path.read_text())["workflows"].values()))["phase"],
                         "pushed")

    def test_direct_action_with_default_approvals_still_requires_confirmation(self):
        result = self.invoke_cli("op=3", "skipApproves=false")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Interactive confirmation required", result.stderr)
        self.assertFalse((self.root / "new.txt").exists())

    def test_direct_action_rejects_invalid_options_and_strict_guard_is_not_skipped(self):
        for arguments in (("op=11",), ("op=UNKNOWN",), ("skipApproves=sometimes",)):
            with self.subTest(arguments=arguments):
                result = self.invoke_cli(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("error:", result.stderr)
        rejected = self.invoke_cli("--strict", "op=5", "skipApproves=true")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("Action unavailable: requires phase: verified", rejected.stderr)

    def test_direct_action_reapply_duplicate_auto_approves_duplicate_prompt(self):
        self.history_path.write_text(f"{self.zip.name}\n")
        result = self.invoke_cli("op=3", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Duplicate patch reapplication [auto-approved", result.stdout)
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 1)

    def test_direct_action_auto_approval_still_backs_up_overlapping_manual_edits(self):
        (self.root / "existing.txt").write_text("manual changes before patch\n")
        result = self.invoke_cli("op=3", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Backed up 1 overlapping file", result.stdout)
        backups = list((self.root / ".apatch" / "backups").glob("overlap-*/existing.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "manual changes before patch\n")
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")

    def test_direct_action_auto_approval_never_overrides_non_fast_forward_safety(self):
        self.assertEqual(self.invoke_cli("op=3", "skipApproves=true").returncode, 0)
        self.assertEqual(self.invoke_cli("op=5", "skipApproves=true").returncode, 0)
        other = self.base / "another_checkout"
        command("git", "clone", "-b", "main", str(self.remote), str(other), cwd=self.base)
        command("git", "config", "user.email", "other@example.test", cwd=other)
        command("git", "config", "user.name", "Other Developer", cwd=other)
        command("git", "commit", "--allow-empty", "-m", "Remote changed", cwd=other)
        command("git", "push", "origin", "main", cwd=other)
        remote_sha = command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                             cwd=self.root).stdout.split()[0]
        rejected = self.invoke_cli("op=6", "skipApproves=true")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("never force-pushes", rejected.stderr)
        self.assertEqual(command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                                 cwd=self.root).stdout.split()[0], remote_sha)

    def test_shell_launcher_accepts_named_handoff_in_loose_mode(self):
        self.prepare_test_launcher()
        for args in (("loose", self.params.stem), (self.params.stem, "--loose"),
                     (str(self.params), "loose")):
            with self.subTest(args=args):
                result = subprocess.run(["sh", str(self.bin / "apatch.sh"), *args],
                                        cwd=self.root,
                                        input="0\n", capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Mode: LOOSE", result.stdout)

    def test_shell_launcher_executes_sequence_with_legacy_named_handoff(self):
        self.prepare_test_launcher()
        result = subprocess.run(["sh", str(self.bin / "apatch.sh"), self.params.stem,
                                 "opSeq=APL,CHK", "skipApproves=true"], cwd=self.root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SEQUENCE RESULT: SUCCESS | completed: 3 [APL], 4 [CHK]", result.stdout)

    def test_shell_launcher_handles_direct_actions_and_strict_mode(self):
        self.prepare_test_launcher()
        for arguments, expected_mode in (((self.params.stem,), "LOOSE"),
                                         ((self.params.stem, "op=0"), "LOOSE"),
                                         (("strict", self.params.stem, "op=0"), "STRICT"),
                                         ((str(self.params), "strict", "op=0"), "STRICT"),
                                         (("force", self.params.stem, "op=0", "skipApproves=true"), "FORCE")):
            with self.subTest(arguments=arguments):
                result = subprocess.run(["sh", str(self.bin / "apatch.sh"), *arguments],
                                        cwd=self.root, input="0\n" if len(arguments) == 1 else "",
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"Mode: {expected_mode}", result.stdout)
                if arguments and "op=0" in arguments:
                    self.assertIn("Selected action via op=0", result.stdout)

    def test_runtime_state_and_history_paths_must_be_relative_filenames(self):
        conf = self.bin / "apatch.conf"
        conf.write_text(conf.read_text().replace("applied_patches_file = applied_patches.txt",
                                                f"applied_patches_file = {self.root / 'patches.txt'}"))
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("plain filenames inside .apatch", result.stderr)
        self.assertFalse((self.root / "patches.txt").exists())

    def test_project_can_override_runtime_filenames(self):
        self.project_config.write_text(
            'schema_version: 1\nstate_file: checkpoint.json\n'
            'applied_patches_file: history.txt\nchecks:\n  - ./run_checks.sh\n')
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / ".apatch" / "checkpoint.json.lock").exists())
        self.assertFalse(self.lock_path.exists())
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         " M .apatch/config.yaml\n")

    def test_project_rejects_traversing_or_conflicting_runtime_names(self):
        cases = [
            ('state_file: ../escape\n', "plain filenames inside .apatch"),
            ('applied_patches_file: /tmp/history\n', "plain filenames inside .apatch"),
            ('state_file: duplicate.txt\napplied_patches_file: duplicate.txt\n', "separate filenames"),
        ]
        for settings, message in cases:
            with self.subTest(settings=settings):
                self.project_config.write_text(
                    f'schema_version: 1\n{settings}checks:\n  - ./run_checks.sh\n')
                result = self.invoke("0\n")
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
