"""Black-box code-review stage and provider contract regression tests."""

from tests._support import LocalGitFixture, command, json, sys, unittest
import hashlib
import stat


class CodeReviewTests(LocalGitFixture):
    def configure_reviewers(self, reviewers, *, required=False, timeout=30, max_bytes=131072,
                            artifacts=False, artifact_max=8388608):
        data = ("schema_version: 1\n"
                "checks:\n  - [\"./run_checks.sh\"]\n"
                f"review_required: {str(required).lower()}\n"
                f"review_timeout_seconds: {timeout}\n"
                f"review_max_bytes: {max_bytes}\n"
                f"review_artifacts_enabled: {str(artifacts).lower()}\n"
                f"review_artifact_max_bytes: {artifact_max}\n"
                "reviewers:\n")
        data += "".join("  - " + json.dumps(item) + "\n" for item in reviewers)
        self.configure_checks(data)

    def structured(self, scanner_specs, tool_results):
        payload = json.dumps({"schema_version": 1, "tools": tool_results})
        return {"id": "static", "kind": "script",
                "command": [sys.executable, "-c", "print(" + repr(payload) + ")"],
                "report_format": "apatch-json-v1", "scanners": scanner_specs}

    def test_structured_review_persists_normalized_report_and_blocks_high_findings(self):
        scanners = [{"id": "bandit", "format": "bandit-json", "required": True}]
        report = {"id": "bandit", "status": "FINDINGS", "format": "bandit-json", "report": {
            "errors": [], "results": [{"test_id": "B602", "issue_severity": "HIGH",
                                    "filename": "existing.txt", "line_number": 1,
                                    "issue_text": "Unsafe command"}]}}
        self.configure_reviewers([self.structured(scanners, [report])], artifacts=True, required=True)
        self.ready()
        result = self.invoke_zip("opSeq=REV,CMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("REVIEW_CHANGES_REQUIRED", result.stderr)
        directory, manifest = self._artifact()
        raw = (directory / "static.stdout").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest["providers"][0]["stdout_sha256"])
        path = directory / manifest["providers"][0]["normalized_file"]
        normalized = json.loads(path.read_text())
        self.assertEqual(normalized["verdict"], "CHANGES_REQUIRED")
        self.assertEqual(normalized["findings"][0]["path"], "existing.txt")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(manifest["status"], "COMPLETED")
        self.assertIn("REVIEW_REQUIRED", self.invoke_zip("op=CMT", "skipApproves=true").stderr)

    def test_structured_missing_required_scanner_escalates_and_advisory_missing_warns(self):
        mandatory = [{"id": "ruff", "format": "ruff-json", "required": True}]
        self.configure_reviewers([self.structured(mandatory, [])], artifacts=True, required=True)
        self.ready()
        missing = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("REVIEW_ESCALATE", missing.stderr)
        directory, manifest = self._artifact()
        self.assertEqual(json.loads((directory / "static.normalized.json").read_text())["verdict"], "ESCALATE")

    def test_structured_zero_findings_allows_required_review_to_commit(self):
        scanners = [{"id": "ruff", "format": "ruff-json", "required": True}]
        report = {"id": "ruff", "status": "SUCCEEDED", "format": "ruff-json", "report": []}
        self.configure_reviewers([self.structured(scanners, [report])], artifacts=True, required=True)
        self.ready()
        passed = self.invoke_zip("opSeq=REV,CMT", "skipApproves=true")
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        self.assertIn("CODE REVIEW: PASS", passed.stdout)

    def test_structured_report_requires_capture_and_configured_scanner_policy(self):
        reviewers = [self.structured([{"id": "ruff", "format": "ruff-json", "required": True}], [])]
        self.configure_reviewers(reviewers, artifacts=False)
        result = self.invoke_zip("op=STS")
        self.assertEqual(result.returncode, 2)
        self.assertIn("review_artifacts_enabled", result.stderr)
        self.configure_reviewers(reviewers, artifacts=True)
        original = self.project_config.read_text()
        self.project_config.write_text(original.replace('"required": true', '"required": "yes"'))
        result = self.invoke_zip("op=STS")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid scanner policy", result.stderr)

    def ready(self, *, checked=True):
        stem = self.make_self_contained_zip()
        actions = "APL,BRN,CHK" if checked else "APL,BRN"
        result = self.invoke_zip("opSeq=" + actions, "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def script(self, code="print('static checks passed')"):
        return {"id": "static", "kind": "script",
                "command": [sys.executable, "-c", code]}

    def llm(self, result, *, envelope=False):
        payload = json.dumps(result)
        if envelope:
            payload = json.dumps({"response": payload})
        code = "import sys; text=sys.stdin.read(); assert 'existing.txt' in text; print(" + repr(payload) + ")"
        return {"id": "gemini", "kind": "llm", "model": "custom-model",
                "command": [sys.executable, "-c", code, "{model}"]}

    def test_script_review_runs_after_chk_and_is_recorded(self):
        self.configure_reviewers([self.script()])
        self.ready()
        result = self.invoke_zip("opSeq=REV,STS", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("13 [REV]", result.stdout)
        self.assertIn("static checks passed", result.stdout)
        self.assertIn("CODE REVIEW: PASS", result.stdout)
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["code_review"]["verdict"], "PASS")
        runs = [r for r in state["operation_runs"] if r["operation"]["code"] == "REV"]
        self.assertEqual(runs[-1]["outcome"], "SUCCEEDED")

    def _artifact(self):
        directories = list((self.root / ".apatch" / "reviews").glob("review-*"))
        self.assertEqual(len(directories), 1)
        directory = directories[0]
        return directory, json.loads((directory / "manifest.json").read_text())

    def test_opt_in_capture_keeps_complete_script_stdout_stderr_and_private_manifest(self):
        code = ("import sys; print('A' * 400000); "
                "sys.stderr.write('diagnostic\\n')")
        self.configure_reviewers([self.script(code)], artifacts=True)
        self.ready()
        completed = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        directory, manifest = self._artifact()
        self.assertEqual(manifest["status"], "COMPLETED")
        item = manifest["providers"][0]
        stdout = (directory / item["stdout_file"]).read_bytes()
        stderr = (directory / item["stderr_file"]).read_bytes()
        self.assertEqual(len(stdout), 400001)
        self.assertEqual(stderr, b"diagnostic\n")
        self.assertEqual(item["stdout_sha256"], hashlib.sha256(stdout).hexdigest())
        self.assertEqual(item["stderr_sha256"], hashlib.sha256(stderr).hexdigest())
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for path in (directory / "manifest.json", directory / item["stdout_file"],
                     directory / item["stderr_file"]):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["code_review"]["artifact_path"],
                         directory.relative_to(self.root).as_posix())
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, " M existing.txt\n?? new.txt\n")

    def test_capture_retains_failed_provider_evidence_but_never_passes(self):
        self.configure_reviewers([self.script("import sys; print('warning'); sys.exit(5)")],
                                 artifacts=True, required=True)
        self.ready()
        failed = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("REVIEW_FAILED", failed.stderr)
        directory, manifest = self._artifact()
        self.assertEqual(manifest["status"], "FAILED")
        self.assertEqual(manifest["providers"][0]["exit_code"], 5)
        self.assertIn(b"warning", (directory / "static.stdout").read_bytes())
        blocked = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertIn("REVIEW_REQUIRED", blocked.stderr)

    def test_capture_exceeding_output_cap_fails_closed_and_marks_truncation(self):
        self.configure_reviewers([self.script("print('B' * 200000)")], artifacts=True,
                                 artifact_max=65536)
        self.ready()
        failed = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("REVIEW_OUTPUT_TOO_LARGE", failed.stderr)
        directory, manifest = self._artifact()
        self.assertEqual(manifest["status"], "FAILED")
        self.assertTrue(manifest["providers"][0]["truncated"])
        self.assertLessEqual(sum(manifest["providers"][0][key]
                                 for key in ("stdout_bytes", "stderr_bytes")), 65536)

    def test_capture_timeout_retains_bounded_partial_report(self):
        self.configure_reviewers([self.script(
            "import sys,time; print('started', flush=True); time.sleep(5)")],
            artifacts=True, timeout=1)
        self.ready()
        failed = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("REVIEW_TIMEOUT", failed.stderr)
        directory, manifest = self._artifact()
        self.assertEqual(manifest["status"], "FAILED")
        self.assertTrue(manifest["providers"][0]["timed_out"])
        stdout = (directory / "static.stdout").read_bytes()
        self.assertEqual(manifest["providers"][0]["stdout_bytes"], len(stdout))

    def test_capture_config_validation_rejects_invalid_types_and_limits(self):
        self.configure_reviewers([self.script()], artifacts=True)
        original = self.project_config.read_text()
        for value in ('"true"', '1'):
            with self.subTest(enabled=value):
                self.project_config.write_text(original.replace(
                    "review_artifacts_enabled: true", "review_artifacts_enabled: " + value))
                failed = self.invoke_zip("op=STS")
                self.assertEqual(failed.returncode, 2)
                self.assertIn("review_artifacts_enabled", failed.stderr)
        self.project_config.write_text(original.replace(
            "review_artifact_max_bytes: 8388608", "review_artifact_max_bytes: 1024"))
        failed = self.invoke_zip("op=STS")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("review_artifact_max_bytes", failed.stderr)

    def test_symlinked_review_storage_is_rejected_before_provider_runs(self):
        self.configure_reviewers([self.script("print('should-not-run')")], artifacts=True)
        self.ready()
        directory = self.root / ".apatch" / "reviews"
        outside = self.base / "external"
        outside.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
        failed = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("REVIEW_ARTIFACT_UNSAFE", failed.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_capture_llm_still_requires_structured_verdict(self):
        self.configure_reviewers([self.llm({"verdict": "PASS", "summary": "ok", "findings": []})],
                                 artifacts=True)
        self.ready()
        result = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        directory, manifest = self._artifact()
        self.assertEqual(manifest["providers"][0]["kind"], "llm")
        self.assertIn(b'"verdict"', (directory / "gemini.stdout").read_bytes())

    def test_review_requires_canonical_check_and_configuration(self):
        self.ready(checked=False)
        result = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires reviewers", result.stderr)

    def test_required_review_blocks_commit_until_passed(self):
        self.configure_reviewers([self.script()], required=True)
        self.ready()
        status = self.invoke_zip("op=STS")
        self.assertIn("Next suggested: 13 [REV]", status.stdout)
        refused = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("REVIEW_REQUIRED", refused.stderr)
        reviewed = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
        committed = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)

    def test_review_with_model_envelope_and_several_providers(self):
        self.configure_reviewers([
            self.script(), self.llm({"verdict": "PASS", "summary": "Looks safe", "findings": []},
                                   envelope=True)], required=True)
        self.ready()
        checked = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("model=custom-model", checked.stdout)
        self.assertIn("Looks safe", checked.stdout)
        self.assertIn("2 reviewer(s)", checked.stdout)

    def test_llm_changes_required_stops_sequence_and_persists_report(self):
        self.configure_reviewers([self.llm({
            "verdict": "CHANGES_REQUIRED", "summary": "A validation case is missing",
            "findings": [{"severity": "high", "file": "new.txt", "message": "Add tests"}]
        })], required=True)
        self.ready()
        result = self.invoke_zip("opSeq=REV,CMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("REVIEW_CHANGES_REQUIRED", result.stderr)
        self.assertIn("Remaining (not executed): 5 [CMT]", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertEqual(record["code_review"]["verdict"], "CHANGES_REQUIRED")

    def test_model_response_must_have_unambiguous_verdict(self):
        self.configure_reviewers([self.llm({"summary": "Everything seems fine"})])
        self.ready()
        result = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("REVIEW_INVALID_RESPONSE", result.stderr)

    def test_modified_files_invalidate_required_review(self):
        self.configure_reviewers([self.script()], required=True)
        self.ready()
        self.assertEqual(self.invoke_zip("op=REV", "skipApproves=true").returncode, 0)
        (self.root / "existing.txt").write_text("changed after review\n")
        result = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("REVIEW_REQUIRED", result.stderr)

    def test_review_script_that_changes_worktree_fails_closed(self):
        code = "from pathlib import Path; Path('existing.txt').write_text('surprise\\n')"
        self.configure_reviewers([self.script(code)])
        self.ready()
        result = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("REVIEW_WORKTREE_CHANGED", result.stderr)
        self.assertEqual((self.root / "existing.txt").read_text(), "surprise\n")

    def test_too_large_bundle_never_invokes_external_provider(self):
        self.configure_reviewers([self.script("from pathlib import Path; Path('marker').touch()")],
                                 max_bytes=1024)
        self.ready()
        (self.root / "big.txt").write_text("x" * 2000)
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        result = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("REVIEW_TOO_LARGE", result.stderr)
        self.assertFalse((self.root / "marker").exists())

    def test_required_goal_includes_rev_before_commit(self):
        self.configure_reviewers([self.script()], required=True)
        stem = self.make_self_contained_zip()
        preview = self.invoke_zip("goal=COMMITTED", "planOnly=true", selection=stem)
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        self.assertIn("CHK, REV, CMT", preview.stdout)

    def test_guarded_committed_goal_executes_review_before_commit(self):
        self.configure_reviewers([self.script()], required=True)
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("goal=COMMITTED", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GOAL STEP: REV", result.stdout)
        self.assertIn("CODE REVIEW: PASS", result.stdout)
        self.assertIn("GOAL STEP: CMT", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])

    def test_rechecking_invalidates_prior_review(self):
        self.configure_reviewers([self.script()], required=True)
        self.ready()
        self.assertEqual(self.invoke_zip("op=REV", "skipApproves=true").returncode, 0)
        self.assertEqual(self.invoke_zip("op=CHK", "skipApproves=true").returncode, 0)
        result = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("REVIEW_REQUIRED", result.stderr)


if __name__ == "__main__":
    unittest.main()
