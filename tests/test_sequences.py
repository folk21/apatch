"""Regression tests for the sequences subsystem."""

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


class SequencesTests(LocalGitFixture):
    def test_operation_sequence_parses_numbers_and_codes_and_rejects_unsafe_forms(self):
        self.assertEqual(OperationSequence.parse("3, CHK,5, PSH").actions, (3, 4, 5, 6))
        self.assertEqual(OperationSequence.parse("STS,9,10").actions, (10, 9, 10))
        for invalid in ("", "APL,", ",APL", "APL,,CHK", "unknown,CHK", "0,APL",
                        "APL,APL", "BAP,APL", ",".join(["CHK"] * 21)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                OperationSequence.parse(invalid)

    def test_sequence_executes_all_actions_without_prompts_and_preserves_git_guards(self):
        result = self.invoke_cli("opSeq=APL,CHK,CMT,PSH", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SEQUENCE ACTION 3 [APL]", result.stdout)
        self.assertIn("SEQUENCE ACTION 6 [PSH]", result.stdout)
        self.assertIn("Next scheduled: 4 [CHK]", result.stdout)
        self.assertIn("SEQUENCE RESULT: SUCCESS | completed: 3 [APL], 4 [CHK], 5 [CMT], 6 [PSH]", result.stdout)
        self.assertNotIn("SEQUENCE STEP", result.stdout)
        self.assertIn("RESULT 3 [APL]: SUCCESS", result.stdout)
        self.assertNotIn("Type YES to continue:", result.stdout)
        self.assertNotRegex(result.stdout, r"\x1b\[[0-9;]*m")
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         command("git", "ls-remote", "--heads", "origin", "refs/heads/main",
                                 cwd=self.root).stdout.split()[0])

    def test_sequence_creates_feature_branch_then_applies_and_checks(self):
        result = self.invoke_cli("opSeq=BRN,APL,CHK", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SEQUENCE RESULT: SUCCESS | completed: 1 [BRN], 3 [APL], 4 [CHK]", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])
        self.assertEqual(next(iter(json.loads(self.state_path.read_text())["workflows"].values()))["phase"],
                         "verified")

    def test_sequence_stops_on_second_action_failure_without_committing(self):
        self.project_config.write_text('schema_version: 1\nchecks:\n  - ["false"]\n')
        result = self.invoke_cli("opSeq=APL,CHK,CMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("SEQUENCE STOP: 4 [CHK] | last confirmed: 3 [APL]", result.stdout)
        self.assertIn("Remaining (not executed): 5 [CMT]", result.stdout)
        self.assertIn("RESULT 4 [CHK]: ERROR", result.stdout)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)
        self.assertEqual(next(iter(json.loads(self.state_path.read_text())["workflows"].values()))["phase"],
                         "patch_applied")

    def test_sequence_requires_explicit_unattended_approval_and_stops_on_cancel(self):
        result = self.invoke_cli("opSeq=APL,CHK,CMT")
        self.assertEqual(result.returncode, 2)
        self.assertIn("SEQUENCE STOP: 3 [APL] | last confirmed: NONE", result.stdout)
        self.assertIn("Interactive confirmation required", result.stderr)
        self.assertFalse((self.root / "new.txt").exists())

    def test_sequence_stops_when_a_later_commit_confirmation_is_declined(self):
        result = self.invoke_cli("opSeq=APL,CHK,CMT,PSH", text="YES\nYES\nNO\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("RESULT 5 [CMT]: CANCELLED", result.stdout)
        self.assertIn("SEQUENCE STOP: 5 [CMT]", result.stdout)
        self.assertIn("remaining (not executed): 6 [PSH]", result.stdout)
        self.assertNotIn("SEQUENCE ACTION 6 [PSH]", result.stdout)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)

    def test_sequence_cli_rejects_conflicts_and_duplicates_before_mutations(self):
        for options in (("opSeq=APL,",), ("opSeq=APL,APL",),
                        ("opSeq=EXT,CHK",), ("op=APL", "opSeq=CHK"),
                        ("opSeq=ALP,CHK",), ("opSeq=APL", "patch=any.zip")):
            with self.subTest(options=options):
                result = self.invoke_cli(*options, "skipApproves=true")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)
                self.assertFalse((self.root / "new.txt").exists())

    def test_sequence_skipped_validation_cannot_override_strict_phase(self):
        result = self.invoke_cli("--strict", "opSeq=CMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Action unavailable: requires phase: verified", result.stderr)
        self.assertIn("SEQUENCE STOP: 5 [CMT]", result.stdout)

    def test_sequence_can_end_with_status_report_after_check(self):
        result = self.invoke_cli("opSeq=APL,CHK,STS", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Next scheduled: 10 [STS]", result.stdout)
        self.assertIn("SEQUENCE ACTION 10 [STS]", result.stdout)
        self.assertIn("PATCH STATUS 10 [STS]", result.stdout)
        self.assertIn("SEQUENCE REPORT 10 [STS]: DISPLAYED (read-only)", result.stdout)
        self.assertIn("SEQUENCE RESULT: SUCCESS | completed: 3 [APL], 4 [CHK], 10 [STS]", result.stdout)
        self.assertNotIn("SEQUENCE STEP", result.stdout)
        self.assertEqual(next(iter(json.loads(self.state_path.read_text())["workflows"].values()))["phase"],
                         "verified")

    def test_formatter_changes_existing_bytes_without_changing_paths_stops_sequence_and_recovers(self):
        runner = self.root / "run_checks.sh"
        runner.write_text(
            "#!/bin/sh\nset -eu\ntest -f new.txt\n"
            "if ! grep -q '^formatted$' existing.txt; then\n"
            "  printf 'formatted\\n' > existing.txt\n"
            "fi\n"
        )
        runner.chmod(0o755)
        result = self.invoke_cli("opSeq=APL,CHK,STS", "skipApproves=true")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("RESULT 3 [APL]: SUCCESS", result.stdout)
        self.assertIn("RESULT 4 [CHK]: ERROR", result.stdout)
        self.assertNotIn("RESULT 4 [CHK]: NO_OP", result.stdout)
        self.assertIn("Phase: patch_applied -> patch_applied", result.stdout)
        self.assertIn("Next suggested: 4 [CHK]", result.stdout)
        self.assertIn("opSeq=CHK,STS", result.stdout)
        self.assertIn("CHECKS_CHANGED_WORKTREE", result.stderr)
        self.assertIn("Remaining (not executed): 10 [STS]", result.stdout)
        self.assertNotIn("PATCH STATUS 10 [STS]", result.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "formatted\n")
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["phase"], "patch_applied")
        self.assertNotIn("verified_fingerprint", record)
        self.assertEqual([run["outcome"] for run in state["operation_runs"]],
                         ["SUCCEEDED", "FAILED"])

        resumed = self.invoke_cli("opSeq=CHK,STS", "skipApproves=true")
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertIn("RESULT 4 [CHK]: SUCCESS", resumed.stdout)
        self.assertIn("Checks passed: YES", resumed.stdout)
        self.assertEqual(next(iter(json.loads(self.state_path.read_text())["workflows"].values()))["phase"],
                         "verified")

    def test_direct_check_invalidated_after_prior_success_clears_stale_evidence(self):
        applied_and_verified = self.invoke_cli("opSeq=APL,CHK", "skipApproves=true")
        self.assertEqual(applied_and_verified.returncode, 0,
                         applied_and_verified.stdout + applied_and_verified.stderr)
        original = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertIn("verified_fingerprint", original)
        self.assertIn("verified_head", original)
        self.assertIn("verified_branch", original)

        runner = self.root / "run_checks.sh"
        runner.write_text("#!/bin/sh\nset -eu\n"
                          "test -f new.txt\nprintf 'formatted\\n' > existing.txt\n")
        runner.chmod(0o755)
        result = self.invoke_cli("op=CHK", "skipApproves=true")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("RESULT 4 [CHK]: ERROR", result.stdout)
        self.assertIn("CHECKS_CHANGED_WORKTREE", result.stderr)
        self.assertEqual((self.root / "existing.txt").read_text(), "formatted\n")
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertEqual(record["phase"], "patch_applied")
        for key in ("verified_fingerprint", "verified_head", "verified_branch", "verified_commit"):
            self.assertNotIn(key, record)

        status = self.invoke_cli("op=STS")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("Checks passed: PENDING", status.stdout)
        self.assertIn("Next suggested: 4 [CHK]", status.stdout)

    def test_read_only_status_sequence_does_not_initialize_workflow_files(self):
        self.zip.unlink()
        exclude = self.root / ".git" / "info" / "exclude"
        before_exclude = exclude.read_bytes()
        result = self.invoke_cli("opSeq=STS", "patch=" + self.zip.name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PATCH STATUS 10 [STS]", result.stdout)
        for path in (self.state_path, self.lock_path, self.log_path, self.history_path):
            self.assertFalse(path.exists(), str(path))
        self.assertEqual(exclude.read_bytes(), before_exclude)

    def test_status_in_sequence_is_read_only_and_does_not_prevent_later_action(self):
        result = self.invoke_cli("opSeq=STS,APL,STS", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("PATCH STATUS 10 [STS]"), 2)
        self.assertIn("Next scheduled: 3 [APL]", result.stdout)
        self.assertIn("SEQUENCE RESULT: SUCCESS | completed: 10 [STS], 3 [APL], 10 [STS]", result.stdout)

    def test_verified_sync_no_op_allows_final_status_but_ordinary_no_op_fails(self):
        class ReverifiedWorkflow:
            def __init__(self, outcomes):
                self.outcomes = iter(outcomes)
                self.called = []

            def interactive(self, code, *, show_header):
                self.called.append((code, show_header))
                return next(self.outcomes)

        workflow = ReverifiedWorkflow(("SUCCESS", "ALREADY_SATISFIED", "NO_OP"))
        console = StringIO()
        with redirect_stdout(console):
            execute_sequence(workflow, OperationSequence.parse("MRG,SYN,STS"))
        self.assertEqual([code for code, _ in workflow.called], ["MRG", "SYN", "STS"])
        self.assertIn("SEQUENCE CONTINUE: 9 [SYN] already synchronized", console.getvalue())
        self.assertIn("SEQUENCE RESULT: SUCCESS | completed: 8 [MRG], 9 [SYN], 10 [STS]", console.getvalue())
        with redirect_stdout(StringIO()), self.assertRaises(Abort):
            execute_sequence(ReverifiedWorkflow(("NO_OP",)), OperationSequence.parse("SYN,STS"))

    def test_workflow_labels_reverified_syn_as_already_satisfied(self):
        from apatch_lib.workflow import Workflow

        config = load_project_config(self.root, load_config(self.bin))
        workflow = Workflow(self.root, config, load_handoff(self.params),
                            {"schema_version": 1, "workflows": {}},
                            force=True, skip_previous_cycles=True)
        workflow.record["phase"] = "synced"
        console = StringIO()
        with patch.object(workflow.force_actions, "sync", return_value=True), \
                patch("apatch_lib.presentation.execution.inspect_patch", return_value={}), \
                patch("apatch_lib.presentation.execution.display_recommendation"), \
                redirect_stdout(console):
            result = workflow.interactive("SYN")
        self.assertEqual(result, "ALREADY_SATISFIED")
        self.assertIn("RESULT 9 [SYN]: ALREADY_SATISFIED", console.getvalue())

    def test_result_color_is_terminal_only(self):
        with patch("apatch_lib.console.sys.stdout.isatty", return_value=True), \
             patch.dict(os.environ, {"TERM": "xterm", "NO_COLOR": ""}):
            self.assertEqual(outcome_label("ERROR"), "ERROR")
        with patch("apatch_lib.console.sys.stdout.isatty", return_value=True), \
             patch.dict(os.environ, {"TERM": "xterm"}, clear=True):
            self.assertEqual(outcome_label("SUCCESS"), "\033[32mSUCCESS\033[0m")
            self.assertEqual(outcome_label("ERROR"), "\033[31mERROR\033[0m")
            self.assertEqual(outcome_label("UNKNOWN_REMOTE_RESULT"),
                             "\033[33mUNKNOWN_REMOTE_RESULT\033[0m")
        with patch("apatch_lib.console.sys.stdout.isatty", return_value=False), \
             patch.dict(os.environ, {"TERM": "xterm"}, clear=True):
            self.assertEqual(outcome_label("SUCCESS"), "SUCCESS")
        with patch("apatch_lib.console.sys.stdout.isatty", return_value=True), \
             patch.dict(os.environ, {"TERM": "dumb"}, clear=True):
            self.assertEqual(outcome_label("SUCCESS"), "SUCCESS")

    def test_next_suggested_is_highlighted_only_for_tty(self):
        from apatch_lib.status import PatchStatus, display_recommendation

        status = PatchStatus("example.zip", "feature/example", "verified", "main", {},
                             5, 3, "Review commit scope before proceeding.")

        class FakeTTY(StringIO):
            def isatty(self):
                return True

        tty = FakeTTY()
        with redirect_stdout(tty), patch.dict(os.environ, {"TERM": "xterm"}, clear=True):
            display_recommendation(status)
        self.assertIn("==> \033[1;36mNext suggested: 5 [CMT]\033[0m", tty.getvalue())
        self.assertIn("Alternative: 3 [APL]", tty.getvalue())
        plain = StringIO()
        with redirect_stdout(plain), patch.dict(os.environ, {"TERM": "xterm"}, clear=True):
            display_recommendation(status)
        self.assertIn("==> Next suggested: 5 [CMT]", plain.getvalue())
        self.assertNotIn("\033[", plain.getvalue())
        dumb = FakeTTY()
        with redirect_stdout(dumb), patch.dict(os.environ, {"TERM": "dumb"}, clear=True):
            display_recommendation(status)
        self.assertNotIn("\033[", dumb.getvalue())

    def test_unknown_github_result_is_not_mislabeled_as_error(self):
        from apatch_lib.workflow import Workflow

        config = load_project_config(self.root, load_config(self.bin))
        workflow = Workflow(self.root, config, load_handoff(self.params),
                            {"schema_version": 1, "workflows": {}},
                            force=True, skip_previous_cycles=True)
        workflow.record["phase"] = "pushed"
        console = StringIO()
        with patch.object(workflow.force_actions, "pr",
                          side_effect=RemoteOutcomeUnknown("GitHub PR create result is unknown")), \
                redirect_stdout(console), self.assertRaises(RemoteOutcomeUnknown):
            workflow.interactive("PR")
        self.assertIn("RESULT 7 [PR]: UNKNOWN_REMOTE_RESULT", console.getvalue())
        self.assertNotIn("RESULT 7 [PR]: ERROR", console.getvalue())
        self.assertIn("Inspect the matching GitHub PR", console.getvalue())

    def test_unavailable_action_emits_error_result_banner(self):
        blocked = self.invoke_cli("--strict", "op=CMT", "skipApproves=true")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("RESULT 5 [CMT]: ERROR", blocked.stdout)
        self.assertIn("Action unavailable", blocked.stderr)

    def test_sequence_stops_on_unknown_remote_result_and_preserves_remaining_actions(self):
        class RemoteFailureWorkflow:
            def __init__(self):
                self.calls = []

            def interactive(self, code, *, show_header):
                self.calls.append(code)
                raise RemoteOutcomeUnknown("Request timed out after remote mutation")

        workflow = RemoteFailureWorkflow()
        console = StringIO()
        with redirect_stdout(console), self.assertRaises(RemoteOutcomeUnknown):
            execute_sequence(workflow, OperationSequence.parse("MRG,SYN,STS"))
        self.assertEqual(workflow.calls, ["MRG"])
        self.assertIn("SEQUENCE STOP: 8 [MRG]", console.getvalue())
        self.assertIn("outcome=UNKNOWN_REMOTE_RESULT", console.getvalue())
        self.assertIn("Remaining (not executed): 9 [SYN], 10 [STS]", console.getvalue())
