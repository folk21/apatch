"""AS-06: pure audit rules, contradictory evidence, and bounded presentation."""

import unittest
from pathlib import Path

from apatch_lib.audit_rules import (
    AuditGroups, Finding, finalize_patch_facts, group_audit_records,
    parse_applied_entries, parse_created_entries, reconcile_patch_history,
    reconcile_remote_evidence, reconcile_workflow_records,
)
from apatch_lib.reconciliation import AuditReport, format_audit


class ParsingRulesTests(unittest.TestCase):
    def test_invalid_and_duplicate_created_entries_preserve_valid_names(self) -> None:
        created, findings = parse_created_entries("A.zip\nno/slash.zip\nA.zip\nB.zip\n", Path("created.txt"))
        self.assertEqual(created, ("A.zip", "A.zip", "B.zip"))
        self.assertEqual(tuple(item.code for item in findings),
                         ("INVALID_CREATED_ENTRY", "DUPLICATE_CREATED"))

    def test_invalid_applied_history_is_an_explicit_conflict(self) -> None:
        entries, findings = parse_applied_entries("Patch: missing-fields.zip\n", Path("applied.txt"))
        self.assertEqual(entries, ())
        self.assertEqual(tuple(item.code for item in findings), ("INVALID_APPLIED_HISTORY",))
        self.assertEqual(findings[0].confidence, "CONFLICT")

    def test_order_and_duplicate_detection_do_not_mutate_inputs(self) -> None:
        created = ("A.zip", "B.zip", "C.zip")
        applied = ("A.zip", "C.zip", "C.zip", "unknown.zip")
        findings = reconcile_patch_history(created, applied, Path("created.txt"),
                                           Path("applied.txt"))
        self.assertEqual({item.code for item in findings},
                         {"DUPLICATE_APPLIED", "OUT_OF_ORDER", "MISSING_APPLICATION",
                          "UNREGISTERED_APPLIED"})
        self.assertEqual(created, ("A.zip", "B.zip", "C.zip"))
        self.assertEqual(applied, ("A.zip", "C.zip", "C.zip", "unknown.zip"))


class WorkflowRulesTests(unittest.TestCase):
    def test_grouping_and_checkpoint_reconciliation_preserve_unknown_facts(self) -> None:
        repository = "/tmp/audit-repository"
        state = {
            "schema_version": 2,
            "workflows": {
                "valid": {
                    "repository": repository, "patch_file": "A.zip", "phase": "merged",
                    "branch": "feature/a", "applied_branch": "feature/a",
                    "commit_sha": "f" * 40,
                },
                "invalid": {"repository": repository, "patch_file": "../unsafe.zip"},
            },
            "operation_runs": [{
                "repository": repository, "patch": "A.zip", "outcome": "INDETERMINATE",
                "operation": {"number": 7, "code": "PR"},
            }],
        }
        groups = group_audit_records(state, repository, Path("state.json"),
                                     ("A.zip",), ("A.zip",))
        self.assertEqual(groups.patches, ("A.zip",))
        self.assertEqual(tuple(item.code for item in groups.findings),
                         ("INVALID_WORKFLOW_ID",))
        findings, facts = reconcile_workflow_records(
            groups, ("A.zip",), Path("state.json"), "main",
            {"feature/a": False}, {"f" * 40: False})
        codes = {item.code for item in findings}
        self.assertTrue({"UNFINISHED_WORKFLOW", "MISSING_LOCAL_BRANCH",
                         "MISSING_LOCAL_COMMIT", "PUSH_NOT_RECORDED",
                         "PR_NOT_RECORDED", "UNRESOLVED_OPERATION"}.issubset(codes))
        self.assertEqual(facts["A.zip"], ("local-branch=UNKNOWN", "local-commit=CONFLICT"))

    def test_remote_mismatch_never_turns_recorded_claim_into_verified(self) -> None:
        record = {"patch_file": "A.zip", "phase": "merged", "branch": "feature/a",
                  "pushed_sha": "a" * 40, "pr_number": 12}
        groups = AuditGroups({"A.zip": (record,)}, {}, ("A.zip",), ())
        old = {"A.zip": ("remote=UNKNOWN",)}
        pr = {"number": 12, "headRefName": "feature/a", "baseRefName": "main",
              "headRefOid": "b" * 40, "state": "MERGED", "mergedAt": "2026-10-27T00:00:00Z"}
        findings, facts = reconcile_remote_evidence(
            groups, old, {"feature/a": "b" * 40}, (pr,), True, "main")
        self.assertEqual({item.code for item in findings},
                         {"REMOTE_HEAD_DRIFT", "PR_REVISION_MISMATCH"})
        self.assertEqual(finalize_patch_facts(facts)["A.zip"],
                         ("remote=UNKNOWN", "remote-head=CONFLICT", "pull-request=CONFLICT"))
        self.assertEqual(old, {"A.zip": ("remote=UNKNOWN",)})

    def test_incomplete_remote_listing_does_not_imply_a_missing_pr(self) -> None:
        record = {"patch_file": "A.zip", "phase": "pushed", "branch": "feature/a",
                  "pushed_sha": "a" * 40, "pr_number": 12}
        groups = AuditGroups({"A.zip": (record,)}, {}, ("A.zip",), ())
        findings, facts = reconcile_remote_evidence(
            groups, {"A.zip": ("remote=UNKNOWN",)},
            {"feature/a": "a" * 40}, (), False, "main")
        self.assertNotIn("PR_REVISION_MISMATCH", {item.code for item in findings})
        self.assertEqual(finalize_patch_facts(facts)["A.zip"],
                         ("remote-head=VERIFIED",))


class BoundedReportTests(unittest.TestCase):
    def test_console_report_preserves_existing_field_order_and_labels(self) -> None:
        report = AuditReport(
            Path("/tmp/audit"), ("A.zip",), ("A.zip",), ("A.zip",),
            {"A.zip": [{"phase": "verified"}]}, "a" * 40, "feature/a", 2,
            "UNKNOWN (offline; use verifyRemote=true to query GitHub)",
            {"A.zip": ("local-branch=VERIFIED",)}, (),
        )
        self.assertEqual(format_audit(report), "\n".join((
            "\n==> PATCH AUDIT 11 [AUD] (read-only)",
            "Repository: /tmp/audit",
            "Local HEAD: aaaaaaaaaaaa [VERIFIED] | Branch: feature/a [VERIFIED]",
            "Working-tree changes: 2 [VERIFIED]",
            "Created registry: 1 | Applied entries: 1 | Known patches: 1",
            "Remote: UNKNOWN (offline; use verifyRemote=true to query GitHub)",
            "Findings: ERROR=0 WARNING=0 INFO=0",
            "\nPatch inventory:",
            "  A.zip [RECORDED] created=#1 applied=#1 workflow=verified local-branch=VERIFIED",
            "\nFindings (severity | confidence | patch | code | source):",
            "  No inconsistencies detected in the available evidence.",
            "Audit completed without modifying state, history, Git refs, or worktree.",
        )))

    def test_display_limits_do_not_truncate_report_evidence(self) -> None:
        names = tuple(f"p{index:03}.zip" for index in range(110))
        findings = tuple(Finding("WARNING", "UNKNOWN", name, "TEST", "test", "detail", "inspect")
                         for name in names)
        report = AuditReport(
            Path("/tmp/audit"), names, (), names, {}, "a" * 40, "main", 0,
            "UNKNOWN (offline; use verifyRemote=true to query GitHub)",
            {name: () for name in names}, findings)
        output = format_audit(report)
        self.assertIn("10 additional patches omitted from display", output)
        self.assertIn("10 additional findings omitted from display", output)
        self.assertEqual(len(report.findings), 110)
        self.assertEqual(len(report.patches), 110)


if __name__ == "__main__":
    unittest.main()
