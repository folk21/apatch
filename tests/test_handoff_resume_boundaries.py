"""R3.7 typed ZIP resume verification and legacy compatibility checks."""

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apatch_lib import application, zip_resume
from apatch_lib.cli_request import parse_request
from apatch_lib.mo_handoff.api import (AppliedZipEvidence, AppliedZipVerifier,
                                   ProjectAppliedZipVerifier)
from apatch_lib.mo_handoff.models import Handoff
from apatch_lib.mo_handoff.resume import models, verification
from apatch_lib.handoff_selection import HandoffSelection, SelectionKind


class AppliedZipVerifierBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("/isolated/example")
        self.handoff = Handoff(
            repository="example", branch="feature/resume-r37",
            patch="example-PATCH-2026-11-18-23-50-resume.zip",
            message="refactor: resume boundary\n\nPreserve exact verification.\n",
            base_commit=None, patch_sha256="a" * 64, delete_paths=(),
        )
        self.config = SimpleNamespace(base="main", state_path=Path("/unused/state"))
        self.selection = HandoffSelection(self.handoff, "selected.zip", SelectionKind.NEW_ZIP)

    def test_cold_import_order_and_identity_preserving_legacy_shim(self):
        commands = (
            "from apatch_lib.model import Handoff; "
            "from apatch_lib.mo_handoff.api import AppliedZipVerifier, ProjectAppliedZipVerifier",
            "from apatch_lib.mo_handoff.api import ProjectAppliedZipVerifier; "
            "from apatch_lib.zip_resume import verify_applied_zip",
            "from apatch_lib.mo_handoff.resume.verification import verify_applied_zip; "
            "from apatch_lib.application import execute_request",
            "from apatch_lib.mo_handoff.resume.service import ProjectAppliedZipVerifier; "
            "from apatch_lib.model import Handoff",
        )
        for script in commands:
            with self.subTest(script=script):
                completed = subprocess.run(
                    [sys.executable, "-B", "-c", script],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIs(zip_resume.verify_applied_zip, verification.verify_applied_zip)
        self.assertIs(zip_resume.handoff_signature, verification.handoff_signature)
        self.assertIs(zip_resume.AppliedZipEvidence, models.AppliedZipEvidence)
        self.assertIs(zip_resume.APPLIED_PHASES, models.APPLIED_PHASES)
        self.assertIsInstance(ProjectAppliedZipVerifier(), AppliedZipVerifier)

    def test_port_delegates_without_mutating_evidence_or_arguments(self):
        state = {"workflows": {}, "operation_runs": []}
        evidence = AppliedZipEvidence(self.handoff.patch, "patch_applied", "main", True)
        verifier = Mock(return_value=evidence)
        port = ProjectAppliedZipVerifier(verify_fn=verifier)
        self.assertEqual(port.verify(self.root, self.config, self.handoff, state), evidence)
        verifier.assert_called_once_with(self.root, self.config, self.handoff, state)
        self.assertEqual(state, {"workflows": {}, "operation_runs": []})

    def test_admission_consumes_injected_verifier_not_legacy_function(self):
        state = {"workflows": {"the key": {
            "phase": "patch_applied", "zip_first": True, "applied_branch": "main",
            "archive_sha256": self.handoff.patch_sha256,
        }}}
        port = Mock(spec=AppliedZipVerifier)
        with patch.object(application, "read_state_snapshot", return_value=state), \
                patch.object(application, "workflow_key", return_value="the key"), \
                patch.object(application, "verify_applied_zip", side_effect=AssertionError):
            result = application._admit_zip_start(
                parse_request(["op=BRN"]),
                SimpleNamespace(root=self.root, config=self.config),
                self.selection, resume_ops=port,
            )
        self.assertEqual(result, (True, False))
        port.verify.assert_called_once_with(self.root, self.config, self.handoff, state)

    def test_dispatch_threads_verifier_into_recovery_and_lifecycle(self):
        from apatch_lib.application import ProjectContext
        config = SimpleNamespace()
        context = ProjectContext(self.root, config, Path("/tool"))
        port = Mock(spec=AppliedZipVerifier)
        cache = Mock()
        request = parse_request(["selected", "op=CHK"])
        with patch.object(application, "load_config", return_value=config), \
                patch.object(application, "_resolve_project", return_value=context), \
                patch.object(application, "resolve_handoffs", return_value=self.selection), \
                patch.object(application, "_admit_zip_start", return_value=(False, True)) as admit, \
                patch.object(application, "_execute_lifecycle") as lifecycle, \
                patch.object(application, "ProgressRecorder"):
            self.assertEqual(application.execute_request(
                request, Path("/tool"), cache_ops=cache, resume_ops=port), 0)
        self.assertIs(admit.call_args.kwargs["resume_ops"], port)
        self.assertIs(lifecycle.call_args.kwargs["resume_ops"], port)
        cache.preflight_write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
