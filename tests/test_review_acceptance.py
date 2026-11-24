"""End-to-end review evidence acceptance at the guarded local CLI boundary."""

import hashlib
import json
import sys

from apatch_lib.model import Abort
from apatch_lib.review_evidence_api import ReviewEvidenceSession
from apatch_lib.review_retention import export_review_summary, prune_review_artifacts
from tests._support import LocalGitFixture, command


class ReviewEvidenceAcceptanceTests(LocalGitFixture):
    """Use a disposable Git repository, local reviewers, and no GitHub calls."""

    def setUp(self):
        super().setUp()
        self.configure_checks(self._review_config())
        selected = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN,CHK", "skipApproves=true", selection=selected)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "feature/test-local-handoff")

    @staticmethod
    def _reviewer():
        finding = {"test_id": "B602", "issue_severity": "HIGH",
                   "filename": "existing.txt", "line_number": 1,
                   "issue_text": "PRIVATE_SCAN_MESSAGE"}
        report = {"schema_version": 1, "tools": [
            {"id": "bandit", "status": "FINDINGS", "format": "bandit-json",
             "report": {"errors": [], "results": [finding]}}]}
        script = "print(" + repr(json.dumps(report)) + ")"
        return {"id": "static", "kind": "script",
                "command": [sys.executable, "-c", script],
                "report_format": "apatch-json-v1",
                "scanners": [{"id": "bandit", "format": "bandit-json", "required": True}]}

    def _review_config(self):
        return ("schema_version: 1\nchecks:\n  - [\"./run_checks.sh\"]\n"
                "review_required: true\nreview_artifacts_enabled: true\n"
                "review_retention_enabled: true\nreview_retention_max_runs: 1\n"
                "review_retention_max_bytes: 536870912\nreview_retention_max_age_days: 30\n"
                "reviewers:\n  - " + json.dumps(self._reviewer()) + "\n")

    def _run_review(self):
        result = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertIn("REVIEW_CHANGES_REQUIRED", result.stderr)
        return result

    def _evidence(self):
        directory = next((self.root / ".apatch/reviews").glob("review-*"))
        manifest = json.loads((directory / "manifest.json").read_text())
        report = json.loads((directory / "static.normalized.json").read_text())
        self.assertEqual(manifest["status"], "COMPLETED")
        self.assertEqual(report["verdict"], "CHANGES_REQUIRED")
        self.assertEqual(len(report["findings"]), 1)
        return directory, manifest, report

    def _session(self, directory, manifest):
        snapshot = tuple(manifest["snapshot"])
        original_digest = hashlib.sha256((self.root / "existing.txt").read_bytes()).hexdigest()

        def live_snapshot():
            current = hashlib.sha256((self.root / "existing.txt").read_bytes()).hexdigest()
            return snapshot if current == original_digest else ("SOURCE_DRIFT",)

        return ReviewEvidenceSession(self.root, directory.name, snapshot, live_snapshot)

    def test_review_to_finding_retrieval_and_consented_redacted_export(self):
        """A diagnostic finding can be inspected without authorizing a commit."""
        before = command("git", "status", "--porcelain", cwd=self.root).stdout
        self._run_review()
        directory, manifest, report = self._evidence()
        session = self._session(directory, manifest)
        finding_id = report["findings"][0]["id"]
        document, payload = session.get_review_evidence(directory.name, finding_id, 0)
        self.assertEqual(document, json.loads(payload))
        self.assertEqual(document["scanner_verdict"], "CHANGES_REQUIRED")
        self.assertEqual(document["excerpt"], [{"number": 1, "text": "updated"}])
        self.assertEqual(document["source_sha256"],
                         hashlib.sha256((self.root / "existing.txt").read_bytes()).hexdigest())
        self.assertNotIn(b"PRIVATE_SCAN_MESSAGE", payload)
        with self.assertRaisesRegex(Abort, "REVIEW_EXPORT_CONSENT"):
            export_review_summary(self.root, directory.name)
        exported = export_review_summary(self.root, directory.name, consent=True)
        self.assertEqual(json.loads(exported)["status"], "COMPLETED")
        self.assertIn(b"manifest_sha256", exported)
        self.assertNotIn(b"PRIVATE_SCAN_MESSAGE", exported)
        self.assertNotIn(b"existing.txt", exported)
        self.assertTrue(prune_review_artifacts(self.root).dry_run)
        self.assertTrue(directory.exists())
        blocked = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("REVIEW_REQUIRED", blocked.stderr)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, before)

        (self.root / "existing.txt").write_text("unexpected source edit\n")
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            session.get_review_evidence(directory.name, finding_id, 0)

    def test_retention_removes_only_verified_old_run_and_does_not_change_review_gate(self):
        """The next diagnostic review cannot reuse evidence pruned by retention."""
        self._run_review()
        old, manifest, report = self._evidence()
        first = self._session(old, manifest)
        self._run_review()
        self.assertFalse(old.exists())
        current = list((self.root / ".apatch/reviews").glob("review-*"))
        self.assertEqual(len(current), 1)
        self.assertNotEqual(current[0].name, old.name)
        with self.assertRaisesRegex(Abort, "REVIEW_EXPORT_UNKNOWN"):
            export_review_summary(self.root, old.name, consent=True)
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            first.get_review_evidence(old.name, report["findings"][0]["id"], 0)
        blocked = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("REVIEW_REQUIRED", blocked.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "feature/test-local-handoff")

    def test_mutated_capture_rejected_by_both_retrieval_and_export(self):
        """A changed raw scanner output invalidates both private read paths."""
        self._run_review()
        directory, manifest, report = self._evidence()
        original = command("git", "status", "--porcelain", cwd=self.root).stdout
        raw = directory / "static.stdout"
        raw.write_bytes(raw.read_bytes() + b"tampered")
        session = self._session(directory, manifest)
        with self.assertRaisesRegex(Abort, "REVIEW_EVIDENCE_UNKNOWN"):
            session.get_review_evidence(directory.name, report["findings"][0]["id"], 0)
        with self.assertRaisesRegex(Abort, "REVIEW_EXPORT_UNKNOWN"):
            export_review_summary(self.root, directory.name, consent=True)
        self.assertIn(directory.name, prune_review_artifacts(self.root, max_runs=1).protected)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, original)
        self.assertEqual(self.invoke_zip("op=CMT", "skipApproves=true").returncode, 2)


class ReviewAdmissionAcceptanceTests(LocalGitFixture):
    """Verify legacy default-off behavior and pre-CHK reviewer admission."""

    def _prepare_review(self, *, capture: bool, checked: bool):
        reviewer = {"id": "static", "kind": "script",
                    "command": [sys.executable, "-c", "print('legacy review passed')"]}
        config = ('schema_version: 1\nchecks:\n  - ["./run_checks.sh"]\n'
                  'review_required: true\n'
                  f'review_artifacts_enabled: {str(capture).lower()}\n'
                  'reviewers:\n  - ' + json.dumps(reviewer) + '\n')
        self.configure_checks(config)
        stem = self.make_self_contained_zip()
        sequence = 'opSeq=APL,BRN,CHK' if checked else 'opSeq=APL,BRN'
        result = self.invoke_zip(sequence, 'skipApproves=true', selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_rev_before_chk_does_not_execute_or_allocate_evidence(self):
        """A review cannot run or allocate evidence without verified source."""
        self._prepare_review(capture=True, checked=False)
        before = command('git', 'status', '--porcelain', cwd=self.root).stdout
        refused = self.invoke_zip('op=REV', 'skipApproves=true')
        self.assertEqual(refused.returncode, 2, refused.stderr + refused.stdout)
        self.assertFalse((self.root / '.apatch' / 'reviews').exists())
        self.assertEqual(command('git', 'status', '--porcelain', cwd=self.root).stdout,
                         before)
        record = next(iter(json.loads(self.state_path.read_text())['workflows'].values()))
        self.assertNotIn('code_review', record)

    def test_legacy_script_review_default_capture_off(self):
        """Legacy scripts remain usable without enabling private capture."""
        self._prepare_review(capture=False, checked=True)
        result = self.invoke_zip('op=REV', 'skipApproves=true')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('CODE REVIEW: PASS', result.stdout)
        self.assertFalse((self.root / '.apatch' / 'reviews').exists())
        record = next(iter(json.loads(self.state_path.read_text())['workflows'].values()))
        self.assertEqual(record['code_review']['verdict'], 'PASS')


class PassingReviewAcceptanceTests(LocalGitFixture):
    """Verify passing structured review evidence at the local commit boundary."""

    def setUp(self):
        super().setUp()
        report = {"schema_version": 1, "tools": [
            {"id": "ruff", "status": "SUCCEEDED", "format": "ruff-json", "report": []}]}
        reviewer = {
            "id": "static", "kind": "script",
            "command": [sys.executable, "-c", "print(" + repr(json.dumps(report)) + ")"],
            "report_format": "apatch-json-v1",
            "scanners": [{"id": "ruff", "format": "ruff-json", "required": True}],
        }
        config = ("schema_version: 1\nchecks:\n  - [\"./run_checks.sh\"]\n"
                  "review_required: true\nreview_artifacts_enabled: true\n"
                  "reviewers:\n  - " + json.dumps(reviewer) + "\n")
        self.configure_checks(config)
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip("opSeq=APL,BRN,CHK", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)

    def _pass_review(self):
        result = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("CODE REVIEW: PASS", result.stdout)
        reviews = list((self.root / ".apatch/reviews").glob("review-*"))
        self.assertEqual(len(reviews), 1)
        directory = reviews[0]
        manifest = json.loads((directory / "manifest.json").read_text())
        normalized = json.loads((directory / "static.normalized.json").read_text())
        self.assertEqual(manifest["status"], "COMPLETED")
        self.assertEqual(normalized["verdict"], "PASS")
        self.assertEqual(normalized["findings"], [])
        raw = (directory / "static.stdout").read_bytes()
        self.assertEqual(manifest["providers"][0]["stdout_sha256"],
                         hashlib.sha256(raw).hexdigest())
        return directory

    def test_passing_captured_structured_review_allows_local_commit(self):
        """A fully checked PASS permits only the intended local commit."""
        directory = self._pass_review()
        before = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        result = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        after = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.assertNotEqual(after, before)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        self.assertEqual(command("git", "show", "HEAD:existing.txt", cwd=self.root).stdout,
                         "updated\n")
        self.assertEqual(command("git", "show", "HEAD:new.txt", cwd=self.root).stdout,
                         "new\n")
        self.assertEqual(command("git", "ls-remote", "origin",
                                 "refs/heads/feature/test-local-handoff", cwd=self.root).stdout,
                         "")
        self.assertTrue(directory.exists())
        self.assertNotIn(".apatch/reviews/", command(
            "git", "show", "--format=", "--name-only", "HEAD", cwd=self.root).stdout)

    def test_source_drift_after_passing_review_blocks_commit_without_discarding_edits(self):
        """Review success cannot authorize a changed source tree."""
        directory = self._pass_review()
        before = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        (self.root / "existing.txt").write_text("manual change after review\n")
        refused = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(refused.returncode, 2, refused.stderr + refused.stdout)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         before)
        self.assertEqual((self.root / "existing.txt").read_text(),
                         "manual change after review\n")
        self.assertTrue(directory.exists())
        self.assertEqual(command("git", "ls-remote", "origin",
                                 "refs/heads/feature/test-local-handoff", cwd=self.root).stdout,
                         "")

    def test_source_drift_after_chk_blocks_review_before_capture(self):
        """A stale check cannot start a structured reviewer or allocate evidence."""
        before = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        (self.root / "existing.txt").write_text("manual change after check\n")
        refused = self.invoke_zip("op=REV", "skipApproves=true")
        self.assertEqual(refused.returncode, 2, refused.stderr + refused.stdout)
        self.assertFalse((self.root / ".apatch/reviews").exists())
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         before)
        self.assertEqual((self.root / "existing.txt").read_text(),
                         "manual change after check\n")
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertNotIn("code_review", record)
