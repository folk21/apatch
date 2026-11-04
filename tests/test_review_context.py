"""Deterministic and fail-closed bounded LLM-context tests."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from apatch_lib.model import Abort
from apatch_lib.review_artifacts import ReviewArtifacts
from apatch_lib.review_context import build_review_context


SNAPSHOT = ("feature/test", "a" * 40, "fingerprint", "a.py", "policy")
DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,2 @@
 old
+PRIVATE_DIFF_LINE
"""


def finding(idx, severity="medium", message="PRIVATE_SCANNER_MESSAGE"):
    return {"id": str(idx), "severity": severity, "path": "a.py", "line": 2,
            "message": message, "sources": [{"tool": "scan", "rule": "B602", "index": idx}]}


def report(findings):
    return {"schema_version": 1, "reviewer_id": "static", "snapshot": list(SNAPSHOT),
            "verdict": "PASS", "tools": [{"id": "scan", "status": "FINDINGS",
                                            "required": True, "finding_count": len(findings)}],
            "findings": findings}


class ReviewContextTests(unittest.TestCase):
    def test_deterministic_metadata_only_omits_untrusted_text(self):
        document, payload = build_review_context([report([finding(1)])], SNAPSHOT, DIFF, 4096)
        self.assertLessEqual(len(payload), 4096)
        self.assertNotIn(b"PRIVATE_SCANNER_MESSAGE", payload)
        self.assertNotIn(b"PRIVATE_DIFF_LINE", payload)
        self.assertEqual(document["findings"][0]["rules"], ["B602"])
        self.assertEqual(document, json.loads(payload))
        self.assertEqual(payload, build_review_context([report([finding(1)])], SNAPSHOT, DIFF, 4096)[1])
        self.assertEqual(len(document["snapshot_sha256"]), 64)

    def test_explicit_text_and_diff_are_bounded_and_prioritized(self):
        items = [finding(2, "low", "less important"), finding(1, "high", "urgent")]
        document, payload = build_review_context([report(items)], SNAPSHOT, DIFF, 4096,
                                                 include_messages=True, include_diff=True)
        self.assertLessEqual(len(payload), 4096)
        self.assertEqual([item["severity"] for item in document["findings"]], ["high", "low"])
        self.assertIn(b"PRIVATE_DIFF_LINE", payload)
        self.assertIn(b"urgent", payload)
        self.assertEqual(document["diff_excerpts"][0]["line"], 2)

    def test_low_findings_truncate_and_report_omissions(self):
        items = [finding(i, "low", "M" * 400) for i in range(100)]
        document, payload = build_review_context([report(items)], SNAPSHOT, DIFF, 4096,
                                                 include_messages=True)
        self.assertLessEqual(len(payload), 4096)
        self.assertTrue(document["truncated"])
        self.assertGreater(document["findings_omitted"], 0)
        self.assertEqual(document["findings_total"], 100)

    def test_high_findings_never_silently_drop(self):
        with self.assertRaisesRegex(Abort, "Severe findings exceed"):
            build_review_context([report([finding(i, "high", "M" * 400)
                                         for i in range(100)])], SNAPSHOT, DIFF, 4096,
                                 include_messages=True)

    def test_missing_or_stale_required_evidence_blocks(self):
        with self.assertRaisesRegex(Abort, "No structured"):
            build_review_context([], SNAPSHOT, DIFF, 4096)
        stale = report([])
        stale["snapshot"][1] = "different"
        with self.assertRaisesRegex(Abort, "stale"):
            build_review_context([stale], SNAPSHOT, DIFF, 4096)
        failed = report([])
        failed["tools"][0]["status"] = "UNKNOWN"
        with self.assertRaisesRegex(Abort, "required scanner"):
            build_review_context([failed], SNAPSHOT, DIFF, 4096)

    def test_verified_normalized_rejects_tamper_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "static.stdout"
            source.write_bytes(b"scanner output")
            source.chmod(0o600)
            normalized = report([])
            normalized["raw_stdout_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            dest = root / "static.normalized.json"
            dest.write_text(json.dumps(normalized))
            dest.chmod(0o600)
            artifact = object.__new__(ReviewArtifacts)
            artifact.directory = root
            artifact.max_output_bytes = 65536
            artifact.document = {"providers": [{"id": "static", "stdout_file": source.name,
                "stdout_bytes": source.stat().st_size, "stdout_sha256": normalized["raw_stdout_sha256"],
                "normalized_file": dest.name,
                "normalized_sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}]}
            self.assertEqual(artifact.verified_normalized("static", SNAPSHOT), normalized)
            dest.write_text("tampered")
            with self.assertRaisesRegex(Abort, "digest mismatch"):
                artifact.verified_normalized("static", SNAPSHOT)
            dest.unlink()
            dest.symlink_to(source)
            with self.assertRaisesRegex(Abort, "symlinked"):
                artifact.verified_normalized("static", SNAPSHOT)


if __name__ == "__main__":
    unittest.main()
