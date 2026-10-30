"""Black-box code-review stage and provider contract regression tests."""

from tests._support import LocalGitFixture, command, json, sys, unittest


class CodeReviewTests(LocalGitFixture):
    def configure_reviewers(self, reviewers, *, required=False, timeout=30, max_bytes=131072):
        data = ("schema_version: 1\n"
                "checks:\n  - [\"./run_checks.sh\"]\n"
                f"review_required: {str(required).lower()}\n"
                f"review_timeout_seconds: {timeout}\n"
                f"review_max_bytes: {max_bytes}\n"
                "reviewers:\n")
        data += "".join("  - " + json.dumps(item) + "\n" for item in reviewers)
        self.configure_checks(data)

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
