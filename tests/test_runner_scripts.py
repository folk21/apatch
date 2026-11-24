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

    def test_default_quick_and_regular_run_curated_checks(self):
        for options in ((), ("regular",), ("quick",)):
            with self.subTest(options=options):
                result, args = self.invoke("run_tests.sh", *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(args[:4], ["-B", "-m", "tests.timeout_runner", "-v"])
                self.assertNotIn("discover", args)
                self.assertEqual(len(args), 51)
                self.assertEqual(len(args[4:]), len(set(args[4:])))
                for required in (
                    "tests.test_spec_state",
                    "tests.test_document_frontmatter",
                    "tests.test_feature_traceability",
                    "tests.test_review_normalizer",
                    "tests.test_review_context",
                    "tests.test_review_evidence_api",
                    "tests.test_review_retention",
                    "tests.test_code_review.CodeReviewTests."
                    "test_required_review_blocks_commit_until_passed",
                    "tests.test_session_continuation.SessionContinuationTests."
                    "test_modified_collision_blocks_before_history_or_source_writes",
                    "tests.test_guarded_commit.GuardedCommitTests."
                    "test_unknown_staged_path_blocks_even_with_skip_approves",
                    "tests.test_check_gate.CheckBoundaryTests."
                    "test_default_blocks_cmt_and_chk_unblocks",
                    "tests.test_check_gate.CheckBoundaryTests."
                    "test_merge_gate_rechecks_final_head_and_policy_before_github",
                    "tests.test_check_gate.CheckBoundaryTests."
                    "test_unchecked_commit_on_base_is_rejected_even_when_relaxed",
                    "tests.test_handoffs.HandoffsTests."
                    "test_clean_committed_multi_zip_branch_accepts_explicit_followup",
                    "tests.test_safety.SafetyTests."
                    "test_canonical_check_timeout_stops_batch_and_preserves_commit",
                    "tests.test_artifact_packaging.ArtifactPackagingTests."
                    "test_failed_check_never_produces_zip",
                    "tests.test_runner_scripts",
                    "tests.test_module_prefixes",
                ):
                    self.assertIn(required, args)
                for deferred in (
                    "tests.test_review_acceptance",
                    "tests.test_review_acceptance.ReviewAdmissionAcceptanceTests."
                    "test_rev_before_chk_does_not_execute_or_allocate_evidence",
                    "tests.test_building.BuildActionTests."
                    "test_build_only_runs_build_and_does_not_verify",
                    "tests.test_building",
                    "tests.test_check_gate",
                    "tests.test_branch_reassignment.UpfrontZipBranchSelectionTests",
                    "tests.test_remote_macros.RemoteMacroTests."
                    "test_run_all_new_zip_completes_and_repeated_call_does_not_mutate",
                ):
                    self.assertNotIn(deferred, args)

    def test_rare_launcher_and_full_alias_run_all_tests(self):
        for script, options in (("run_rare_checks.sh", ()), ("run_tests.sh", ("full",))):
            with self.subTest(script=script):
                result, args = self.invoke(script, *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(args, ["-B", "-m", "tests.timeout_runner", "--full"])

    def test_full_discovery_retains_deferred_safety_and_acceptance_cases(self):
        """Moving slow cases out of CHK must not remove them from full verification."""
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(SOURCE_ROOT / "tests"), pattern="test_*.py",
            top_level_dir=str(SOURCE_ROOT))

        def case_ids(group):
            for item in group:
                if isinstance(item, unittest.TestSuite):
                    yield from case_ids(item)
                else:
                    yield item.id()

        ids = set(case_ids(suite))
        for required in (
            "tests.test_review_acceptance.ReviewEvidenceAcceptanceTests."
            "test_mutated_capture_rejected_by_both_retrieval_and_export",
            "tests.test_remote_macros.RemoteMacroTests."
            "test_run_all_new_zip_completes_and_repeated_call_does_not_mutate",
            "tests.test_building.BuildActionTests."
            "test_build_only_runs_build_and_does_not_verify",
            "tests.test_branch_reassignment.UpfrontZipBranchSelectionTests."
            "test_existing_branch_followup_overrides_different_embedded_branch",
            "tests.test_publication_goals.PublicationGoalTests."
            "test_stale_pr_head_blocks_merge_before_mutation",
        ):
            self.assertIn(required, ids)

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

