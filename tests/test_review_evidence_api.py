"""Read-only selective evidence tests using private synthetic review artifacts."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apatch_lib.model import Abort
from apatch_lib.review_evidence_api import ReviewEvidenceSession


REVIEW_ID = "review-" + "a" * 24
FINDING_ID = "b" * 24
SNAPSHOT = ("feature/example", "c" * 40, "fingerprint", "module.py", "policy")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "module.py"
        self.path.write_text("first\nsecond\nthird\nfourth\nfifth\n", encoding="utf-8")
        self.run = self.root / ".apatch/reviews" / REVIEW_ID
        self.run.mkdir(parents=True, mode=0o700)
        self.run.parent.chmod(0o700)
        self.run.chmod(0o700)
        self.source_name = "static"
        self.finding = {"id": FINDING_ID, "path": "module.py", "line": 3,
                        "message": "possible security issue", "severity": "high",
                        "sources": [{"tool": "ruff", "rule": "F401", "index": 0,
                                     "source_id": "d" * 24}]}
        self.raw = b'{"schema_version": 1, "tools": []}'
        self.report = {"schema_version": 1, "reviewer_id": self.source_name,
                       "snapshot": list(SNAPSHOT), "verdict": "CHANGES_REQUIRED",
                       "raw_stdout_sha256": digest(self.raw), "findings": [self.finding]}
        self.rewrite()

    def store(self, filename: str, raw: bytes):
        path = self.run / filename
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    def rewrite(self):
        self.store("static.stdout", self.raw)
        normalized = (json.dumps(self.report, sort_keys=True) + "\n").encode()
        self.store("static.normalized.json", normalized)
        self.manifest = {"schema_version": 1, "review_id": REVIEW_ID,
                         "snapshot": list(SNAPSHOT), "status": "COMPLETED",
                         "providers": [{"id": "static", "stdout_file": "static.stdout",
                                        "stdout_bytes": len(self.raw), "exit_code": 0,
                                        "timed_out": False, "truncated": False,
                                        "stdout_sha256": digest(self.raw),
                                        "normalized_file": "static.normalized.json",
                                        "normalized_sha256": digest(normalized)}]}
        self.store("manifest.json", (json.dumps(self.manifest) + "\n").encode())

    def session(self, **kwargs):
        return ReviewEvidenceSession(self.root, REVIEW_ID, SNAPSHOT,
                                     lambda: SNAPSHOT, **kwargs)

    def test_exact_finding_returns_source_excerpt_with_source_and_evidence_hashes(self):
        session = self.session()
        result, payload = session.get_review_evidence(REVIEW_ID, FINDING_ID, 1)
        self.assertEqual(result, json.loads(payload))
        self.assertEqual(result["path"], "module.py")
        self.assertEqual(result["scanner_verdict"], "CHANGES_REQUIRED")
        self.assertEqual([item["number"] for item in result["excerpt"]], [2, 3, 4])
        self.assertEqual([item["text"] for item in result["excerpt"]],
                         ["second", "third", "fourth"])
        self.assertEqual(result["source_sha256"], digest(self.path.read_bytes()))
        self.assertEqual(result["raw_stdout_sha256"], digest(self.raw))
        self.assertEqual(result["normalized_sha256"], self.manifest["providers"][0]["normalized_sha256"])
        self.assertEqual(session.requests, 1)
        self.assertEqual(session.bytes_returned, len(payload))
        self.assertNotIn(b"possible security issue", payload)

    def test_invalid_identity_and_context_bounds_refused(self):
        for review, finding, count in [(REVIEW_ID + "/../x", FINDING_ID, 0),
                                       (REVIEW_ID, "../../secret", 0),
                                       (REVIEW_ID, FINDING_ID, 21),
                                       (REVIEW_ID, FINDING_ID, True)]:
            with self.subTest(review=review, finding=finding, count=count):
                with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
                    self.session().get_review_evidence(review, finding, count)
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            ReviewEvidenceSession(self.root, "../../run", SNAPSHOT, lambda: SNAPSHOT)

    def test_repeated_requests_and_total_byte_budget_enforced(self):
        session = self.session(max_requests=2, max_total_bytes=16384)
        for _ in range(2):
            session.get_review_evidence(REVIEW_ID, FINDING_ID, 0)
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_BUDGET"):
            session.get_review_evidence(REVIEW_ID, FINDING_ID, 0)
        limited = self.session(max_response_bytes=1024, max_total_bytes=8192)
        self.path.write_text("first\n" + "x" * 900 + "\nthird\n", encoding="utf-8")
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_BUDGET"):
            limited.get_review_evidence(REVIEW_ID, FINDING_ID, 1)

    def test_malformed_manifest_and_incomplete_review_fail_closed(self):
        for key, value in (("status", "FAILED"), ("status", "STARTED"),
                           ("snapshot", ["other"]),
                           ("review_id", "wrong"), ("providers", "not a list")):
            with self.subTest(key=key):
                previous = self.manifest[key]
                self.manifest[key] = value
                self.store("manifest.json", (json.dumps(self.manifest) + "\n").encode())
                with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
                    self.session().get_review_evidence(REVIEW_ID, FINDING_ID)
                self.manifest[key] = previous

    def test_integrity_checks_detect_changed_raw_normalized_and_manifest(self):
        for filename in ("static.stdout", "static.normalized.json"):
            self.rewrite()
            self.store(filename, b"tampered")
            with self.subTest(filename=filename), self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
                self.session().get_review_evidence(REVIEW_ID, FINDING_ID)
        self.rewrite()
        self.store("manifest.json", b"broken-json")
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            self.session().get_review_evidence(REVIEW_ID, FINDING_ID)

    def test_symlinked_storage_and_evidence_files_are_blocked(self):
        for name in ("manifest.json", "static.stdout", "static.normalized.json"):
            self.rewrite()
            path = self.run / name
            backup = self.root / (name + ".backup")
            path.replace(backup)
            path.symlink_to(backup)
            try:
                with self.subTest(name=name), self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
                    self.session().get_review_evidence(REVIEW_ID, FINDING_ID)
            finally:
                path.unlink()
                backup.replace(path)
        self.run.rename(self.run.with_name("older"))
        self.run.symlink_to(self.run.with_name("older"), target_is_directory=True)
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            self.session().get_review_evidence(REVIEW_ID, FINDING_ID)

    def test_source_symlink_directory_and_unsafe_private_path_refused(self):
        target = self.root / "target.py"
        target.write_text("secret\n", encoding="utf-8")
        self.path.unlink()
        self.path.symlink_to(target)
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            self.session().get_review_evidence(REVIEW_ID, FINDING_ID)
        self.path.unlink()
        folder = self.root / "sources"
        folder.mkdir()
        (folder / "module.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
        (self.root / "linked").symlink_to(folder, target_is_directory=True)
        self.finding["path"] = "linked/module.py"
        self.rewrite()
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            self.session().get_review_evidence(REVIEW_ID, FINDING_ID)
        for unsafe in (".apatch/config.yaml", "../secret.txt", "/etc/passwd"):
            self.finding["path"] = unsafe
            self.rewrite()
            with self.subTest(path=unsafe), self.assertRaises(Abort):
                self.session().get_review_evidence(REVIEW_ID, FINDING_ID)

    def test_non_text_oversized_missing_and_too_short_source_refused(self):
        for content in (b"\xff\n\xff\n\xff", b"x" * (1024 * 1024 + 1), b"only\n"):
            self.path.write_bytes(content)
            with self.subTest(size=len(content)), self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
                self.session().get_review_evidence(REVIEW_ID, FINDING_ID)
        self.path.unlink()
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            self.session().get_review_evidence(REVIEW_ID, FINDING_ID)

    def test_incomplete_and_duplicate_scanner_records_are_rejected(self):
        for key, value in (("truncated", True), ("timed_out", True), ("exit_code", 1)):
            self.rewrite()
            self.manifest["providers"][0][key] = value
            self.store("manifest.json", (json.dumps(self.manifest) + "\n").encode())
            with self.subTest(key=key), self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
                self.session().get_review_evidence(REVIEW_ID, FINDING_ID)
            self.manifest["providers"][0][key] = False if key != "exit_code" else 0
        self.rewrite()
        self.manifest["providers"].append(dict(self.manifest["providers"][0]))
        self.store("manifest.json", (json.dumps(self.manifest) + "\n").encode())
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            self.session().get_review_evidence(REVIEW_ID, FINDING_ID)

    def test_missing_and_ambiguous_findings_fail_closed(self):
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            self.session().get_review_evidence(REVIEW_ID, "e" * 24)
        self.report["findings"].append(dict(self.finding))
        self.rewrite()
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            self.session().get_review_evidence(REVIEW_ID, FINDING_ID)

    def test_snapshot_mismatch_before_and_after_source_read(self):
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            ReviewEvidenceSession(self.root, REVIEW_ID, SNAPSHOT,
                                  lambda: ("other", *SNAPSHOT[1:])).get_review_evidence(
                                      REVIEW_ID, FINDING_ID)
        counter = [0]

        def drift():
            counter[0] += 1
            return SNAPSHOT if counter[0] == 1 else ("other", *SNAPSHOT[1:])

        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            ReviewEvidenceSession(self.root, REVIEW_ID, SNAPSHOT, drift).get_review_evidence(
                REVIEW_ID, FINDING_ID)

    def test_retrieval_is_local_and_does_not_call_external_processes(self):
        session = self.session()
        requests = [{"review_id": REVIEW_ID, "finding_id": FINDING_ID, "context_lines": 0}]
        with mock.patch("subprocess.Popen", side_effect=AssertionError("external command")):
            for request in requests:
                result, payload = session.get_review_evidence(**request)
                self.assertEqual(result["finding_id"], FINDING_ID)
                self.assertLessEqual(len(payload), 8192)


if __name__ == "__main__":
    unittest.main()
