"""Unit tests for explicit structured scan envelopes and source safety."""

import json
import tempfile
import unittest
from pathlib import Path

from apatch_lib.model import Abort, ReviewProvider, ScannerPolicy
from apatch_lib.review_normalizer import normalize_report


class ReviewNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "new.py").write_text("x = 1\n")

    def provider(self, *policies):
        return ReviewProvider("static", "script", ("analyzer",), "", "apatch-json-v1", tuple(
            ScannerPolicy(*p) for p in policies))

    def normalize(self, provider, tools):
        return normalize_report(self.root, provider,
                                json.dumps({"schema_version": 1, "tools": tools}).encode(), "a" * 64,
                                ("feature/test", "head", "fingerprint", "files", "policy"))

    def test_four_adapters_and_provenance(self):
        provider = self.provider(("ruff", "ruff-json", True),
                                 ("bandit", "bandit-json", True),
                                 ("semgrep", "semgrep-json", False),
                                 ("sarif", "sarif-2.1.0", False))
        tools = [
            {"id": "ruff", "status": "FINDINGS", "format": "ruff-json", "report": [
                {"code": "F401", "filename": "new.py", "location": {"row": 1}, "message": "Unused import"}]},
            {"id": "bandit", "status": "FINDINGS", "format": "bandit-json", "report": {
                "errors": [], "results": [dict(test_id="B602", issue_severity="HIGH",
                                             filename="new.py", line_number=1,
                                             issue_text="Shell injection")]}},
            {"id": "semgrep", "status": "FINDINGS", "format": "semgrep-json", "report": {
                "errors": [], "results": [dict(check_id="sec.rule", path="new.py", start={"line": 1},
                                             extra={"severity": "ERROR", "message": "Shell injection"})]}},
            {"id": "sarif", "status": "FINDINGS", "format": "sarif-2.1.0", "report": {
                "version": "2.1.0", "runs": [{"results": [{
                    "ruleId": "S100", "level": "warning", "message": {"text": "Potential leak"},
                    "locations": [{"physicalLocation": {
                        "artifactLocation": {"uri": "new.py"}, "region": {"startLine": 1}}}]
                }]}]}}
        ]
        result = self.normalize(provider, tools)
        self.assertEqual(result["verdict"], "CHANGES_REQUIRED")
        self.assertEqual(result["findings_total"], 4)
        self.assertEqual(result["findings_unique"], 3)
        duplicate = next(item for item in result["findings"] if item["message"] == "Shell injection")
        self.assertEqual(len(duplicate["sources"]), 2)
        self.assertEqual(duplicate["severity"], "high")
        self.assertTrue(result["raw_stdout_sha256"])
        self.assertEqual(result, self.normalize(provider, list(reversed(tools))))

    def test_duplicate_json_members_and_nonfinite_values_fail_closed(self):
        provider = self.provider(("ruff", "ruff-json", True))
        for payload in (
            b'{"schema_version":1,"tools":[],"tools":[]}',
            b'{"schema_version":1,"tools":[],"note":NaN}',
            b'{"schema_version":1,"tools":[],"note":Infinity}',
            b'\xff\xfe{invalid}',
        ):
            with self.subTest(payload=payload), self.assertRaisesRegex(Abort, "REVIEW_REPORT_INVALID"):
                normalize_report(self.root, provider, payload, "a" * 64, ())

    def test_required_missing_or_failed_is_escalate_even_with_wrapper_exit_zero(self):
        provider = self.provider(("ruff", "ruff-json", True), ("semgrep", "semgrep-json", False))
        for report in ([], [{"id": "ruff", "status": "FAILED", "format": "ruff-json"}],
                       [{"id": "ruff", "status": "TIMED_OUT", "format": "ruff-json"}]):
            with self.subTest(report=report):
                self.assertEqual(self.normalize(provider, report)["verdict"], "ESCALATE")
        advisory = self.normalize(provider, [{"id": "ruff", "status": "SUCCEEDED",
                                              "format": "ruff-json", "report": []}])
        self.assertEqual(advisory["verdict"], "PASS")
        self.assertEqual(advisory["tools"][1]["status"], "UNKNOWN")

    def test_rejects_status_mismatch_and_unsafe_paths(self):
        provider = self.provider(("ruff", "ruff-json", True))
        cases = [
            {"id": "ruff", "status": "SUCCEEDED", "format": "ruff-json", "report": [
                {"code": "F401", "filename": "new.py", "location": {"row": 1}, "message": "found"}]},
            {"id": "ruff", "status": "FINDINGS", "format": "ruff-json", "report": []},
            {"id": "ruff", "status": "FINDINGS", "format": "ruff-json", "report": [
                {"code": "F401", "filename": "../outside", "location": {"row": 1}, "message": "found"}]},
            {"id": "ruff", "status": "FINDINGS", "format": "ruff-json", "report": [
                {"code": "F401", "filename": "https://host/code", "location": {"row": 1}, "message": "found"}]},
            {"id": "ruff", "status": "FAILED", "format": "ruff-json", "report": []},
        ]
        for report in cases:
            with self.subTest(report=report), self.assertRaisesRegex(Abort, "REVIEW_REPORT_INVALID"):
                self.normalize(provider, [report])
        (self.root / "linked.py").symlink_to(self.root / "new.py")
        with self.assertRaisesRegex(Abort, "symlinked"):
            self.normalize(provider, [{"id": "ruff", "status": "FINDINGS", "format": "ruff-json",
                                       "report": [{"code": "F401", "filename": "linked.py",
                                                   "location": {"row": 1}, "message": "found"}]}])

    def test_advisory_high_finding_is_recorded_without_blocking(self):
        provider = self.provider(("semgrep", "semgrep-json", False))
        result = self.normalize(provider, [{"id": "semgrep", "status": "FINDINGS",
            "format": "semgrep-json", "report": {"results": [
                {"check_id": "security", "path": "new.py", "start": {"line": 1},
                 "extra": {"severity": "ERROR", "message": "Security warning"}}]}}])
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["findings"][0]["severity"], "high")
        self.assertFalse(result["tools"][0]["required"])

    def test_hash_verified_stdout_rejects_mutated_and_symlinked_file(self):
        import hashlib
        from apatch_lib.review_artifacts import ReviewArtifacts

        evidence = self.root / "static.stdout"
        original = b'{"schema_version":1,"tools":[]}'
        evidence.write_bytes(original)
        evidence.chmod(0o600)
        artifacts = object.__new__(ReviewArtifacts)
        artifacts.directory = self.root
        artifacts.max_output_bytes = 65536
        artifacts.document = {"providers": [{"id": "static", "stdout_file": "static.stdout",
            "stdout_bytes": len(original), "stdout_sha256": hashlib.sha256(original).hexdigest()}]}
        self.assertEqual(artifacts.verified_stdout("static")[0], original)
        evidence.write_bytes(b"manually edited")
        with self.assertRaisesRegex(Abort, "REVIEW_ARTIFACT_INTEGRITY"):
            artifacts.verified_stdout("static")
        evidence.unlink()
        evidence.symlink_to(self.root / "new.py")
        with self.assertRaisesRegex(Abort, "REVIEW_ARTIFACT_UNSAFE"):
            artifacts.verified_stdout("static")

    def test_scanner_errors_are_not_an_empty_success(self):
        for fmt, report in [("bandit-json", {"errors": ["scanner failed"], "results": []}),
                            ("semgrep-json", {"errors": ["scanner failed"], "results": []}),
                            ("sarif-2.1.0", {"version": "2.1.0", "runs": [
                                {"invocations": [{"executionSuccessful": False}], "results": []}]})]:
            with self.subTest(fmt=fmt), self.assertRaisesRegex(Abort, "REVIEW_REPORT_INVALID"):
                self.normalize(self.provider(("scan", fmt, True)), [
                    {"id": "scan", "status": "SUCCEEDED", "format": fmt, "report": report}])

    def test_bounded_count_and_duplicate_tool_refused(self):
        provider = self.provider(("ruff", "ruff-json", True))
        result = {"id": "ruff", "status": "FINDINGS", "format": "ruff-json", "report": [
            {"code": "F401", "filename": "new.py", "location": {"row": i + 1},
             "message": f"issue {i}"} for i in range(513)]}
        with self.assertRaisesRegex(Abort, "REVIEW_REPORT_INVALID"):
            self.normalize(provider, [result])
        result["report"] = []
        result["status"] = "SUCCEEDED"
        with self.assertRaisesRegex(Abort, "duplicate"):
            self.normalize(provider, [result, result])


if __name__ == "__main__":
    unittest.main()
