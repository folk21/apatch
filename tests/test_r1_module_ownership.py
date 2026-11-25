"""R1 ownership checks for review, publication, and read-only audit."""

import importlib
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = {
    "mo_review": (
        "code_review", "review_artifacts", "review_context",
        "review_evidence_api", "review_normalizer", "review_retention",
    ),
    "mo_publication": ("github", "branch_guard"),
    "mo_audit": ("audit_collectors", "audit_rules", "reconciliation"),
}


class ModuleOwnershipR1Tests(unittest.TestCase):
    def test_only_canonical_paths_own_implementation(self):
        package = ROOT / "apatch_lib"
        for owner, names in PAIRS.items():
            self.assertTrue((package / owner / "__init__.py").is_file())
            for name in names:
                with self.subTest(owner=owner, name=name):
                    self.assertTrue((package / owner / (name + ".py")).is_file())
                    self.assertFalse((package / (name + ".py")).exists())

    def test_old_and_canonical_imports_share_module_identity_in_both_orders(self):
        pairs = [("apatch_lib." + name, "apatch_lib." + owner + "." + name)
                 for owner, names in PAIRS.items() for name in names]
        for old_first in (True, False):
            script = (
                "import importlib\n"
                "for old, new in " + repr(pairs) + ":\n"
                "    a, b = (old, new) if " + repr(old_first) + " else (new, old)\n"
                "    first = importlib.import_module(a)\n"
                "    second = importlib.import_module(b)\n"
                "    assert first is second, (a,b)\n"
                "    assert first.__spec__.name == new, (first.__spec__.name, new)\n"
                "    assert first.__name__ == new\n"
            )
            result = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=ROOT,
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_audit_public_api_matches_historical_entry_points(self):
        from apatch_lib.mo_audit import api
        from apatch_lib.reconciliation import AuditReport, audit_repository, format_audit
        from apatch_lib.audit_rules import Finding
        self.assertIs(api.audit_repository, audit_repository)
        self.assertIs(api.format_audit, format_audit)
        self.assertIs(api.AuditReport, AuditReport)
        self.assertIs(api.Finding, Finding)

    def test_legacy_patch_seams_resolve_to_canonical_objects(self):
        import apatch_lib.github as legacy_github
        import apatch_lib.mo_publication.github as canonical_github
        import apatch_lib.review_artifacts as legacy_artifacts
        import apatch_lib.mo_review.review_artifacts as canonical_artifacts
        self.assertIs(legacy_github, canonical_github)
        self.assertIs(legacy_artifacts, canonical_artifacts)
