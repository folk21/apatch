"""R4 ownership of Git reads, confirmation, and canonical verification."""

import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apatch_lib.mo_core.api import Abort
from apatch_lib.mo_core.enums import WorkflowPhase


ROOT = Path(__file__).resolve().parents[1]
LEGACY_IMPORTS = (
    ("apatch_lib.building", "apatch_lib.mo_verification.building"),
    ("apatch_lib.formatting", "apatch_lib.mo_verification.formatting"),
    ("apatch_lib.check_gates", "apatch_lib.mo_verification.check_gates"),
)


class R4OwnershipTests(unittest.TestCase):
    def test_canonical_owners_and_legacy_source_removal(self):
        for old, new in LEGACY_IMPORTS:
            old_file = ROOT.joinpath(*old.split(".")).with_suffix(".py")
            new_file = ROOT.joinpath(*new.split(".")).with_suffix(".py")
            self.assertFalse(old_file.exists(), old_file)
            self.assertTrue(new_file.is_file(), new_file)
        for file in (
            "apatch_lib/mo_verification/api.py",
            "apatch_lib/mo_verification/contract.md",
            "apatch_lib/mo_verification/checks.py",
            "apatch_lib/mo_git/repository.py",
            "apatch_lib/mo_presentation/confirmation.py",
        ):
            self.assertTrue((ROOT / file).is_file(), file)

    def test_old_and_canonical_modules_share_identity_both_import_orders(self):
        for legacy_first in (True, False):
            script = (
                "import importlib\n"
                f"for old, new in {LEGACY_IMPORTS!r}:\n"
                f"    first, second = (old, new) if {legacy_first!r} else (new, old)\n"
                "    a = importlib.import_module(first)\n"
                "    b = importlib.import_module(second)\n"
                "    assert a is b, (first, second)\n"
                "    assert a.__spec__.name == new, a.__spec__\n"
            )
            result = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=ROOT,
                capture_output=True, text=True, timeout=25, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_git_facade_keeps_patched_runner_and_public_identity(self):
        from apatch_lib import gitutil
        from apatch_lib.mo_git import repository, api, commands
        self.assertIs(gitutil.run, commands.run)
        self.assertIs(gitutil.output, repository.output)
        self.assertIs(gitutil.head, api.head)
        self.assertIs(gitutil.status_paths, repository.status_paths)
        self.assertIs(gitutil.worktree_fingerprint, api.worktree_fingerprint)
        with patch.object(gitutil, "run", return_value=Mock(stdout="  example\n")) as runner:
            self.assertEqual(repository.output(["git", "rev-parse", "HEAD"], ROOT), "example")
            runner.assert_called_once_with(["git", "rev-parse", "HEAD"], ROOT, timeout=None)

    def test_legacy_repository_helpers_preserve_patchable_read_seams(self):
        from apatch_lib import gitutil
        from apatch_lib.mo_git import repository
        with patch.object(gitutil, "output", return_value="feature/test") as output:
            self.assertEqual(repository.current_branch(ROOT), "feature/test")
            output.assert_called_once_with(["git", "branch", "--show-current"], ROOT)
        with patch.object(gitutil, "status_paths", return_value={}) as paths:
            digest, changed = repository.worktree_fingerprint(ROOT)
            self.assertEqual(changed, {})
            self.assertEqual(len(digest), 64)
            paths.assert_called_once_with(ROOT)

    def test_approval_context_is_shared_and_never_skips_safety_gates(self):
        from apatch_lib import gitutil
        from apatch_lib.mo_presentation import confirmation
        self.assertIs(gitutil.confirm, confirmation.confirm)
        self.assertIs(gitutil.confirmation_was_declined, confirmation.confirmation_was_declined)
        self.assertIs(gitutil._SKIP_APPROVALS, confirmation._SKIP_APPROVALS)
        token = gitutil.set_skip_approvals(True)
        try:
            self.assertTrue(confirmation.confirm("Allow operation?"))
            self.assertTrue(confirmation.skip_approvals_enabled())
        finally:
            confirmation.reset_skip_approvals(token)
        self.assertFalse(gitutil.skip_approvals_enabled())

    def _workflow(self, *, fingerprints=("same", "same")):
        checks = [["python3", "-c", "pass"]]
        record = {"before_patch_head": "a" * 40, "code_review": "old"}
        workflow = SimpleNamespace(
            phase=WorkflowPhase.PATCH_APPLIED,
            root=ROOT,
            applied_branch="feature/test",
            config=SimpleNamespace(checks=checks, check_timeout_seconds=8,
                                   check_idle_timeout_seconds=4),
            record=record,
            assert_remote_unchanged=Mock(),
            assert_patch_identity=Mock(),
            assert_expected_paths=Mock(side_effect=[(value, {"file.py": " M"})
                                                    for value in fingerprints]),
            persist=Mock(),
        )
        return workflow

    def test_chk_delegation_and_success_evidence_match_previous_contract(self):
        from apatch_lib.mo_verification import api
        from apatch_lib.mo_verification import checks
        from apatch_lib.workflow import Workflow
        self.assertIs(api.run_checks, checks.run_checks)
        workflow = self._workflow()
        with patch.object(checks, "require_branch") as branch, \
                patch.object(checks, "head", return_value="a" * 40), \
                patch.object(checks, "run") as command:
            self.assertTrue(Workflow.verify(workflow))
        branch.assert_called_once_with(ROOT, "feature/test")
        self.assertEqual(command.call_count, 2)
        self.assertEqual(command.call_args_list[0].args[0], ["git", "diff", "--check"])
        self.assertEqual(workflow.record["verified_fingerprint"], "same")
        self.assertEqual(workflow.record["phase"], "verified")
        self.assertNotIn("code_review", workflow.record)
        workflow.persist.assert_called_once_with()

    def test_chk_detects_modified_bytes_and_invalidates_evidence(self):
        from apatch_lib.mo_verification import checks
        workflow = self._workflow(fingerprints=("before", "after"))
        with patch.object(checks, "require_branch"), \
                patch.object(checks, "head", return_value="a" * 40), \
                patch.object(checks, "run"):
            with self.assertRaisesRegex(Abort, "Tests changed repository files"):
                checks.run_checks(workflow)
        self.assertEqual(workflow.record["phase"], WorkflowPhase.PATCH_APPLIED.value)
        self.assertNotIn("verified_fingerprint", workflow.record)
        workflow.persist.assert_called_once_with()

    def test_chk_blocks_head_drift_before_running_commands(self):
        from apatch_lib.mo_verification import checks
        workflow = self._workflow()
        with patch.object(checks, "require_branch"), \
                patch.object(checks, "head", return_value="b" * 40), \
                patch.object(checks, "run") as command:
            with self.assertRaisesRegex(Abort, "HEAD drifted"):
                checks.run_checks(workflow)
        command.assert_not_called()
        workflow.persist.assert_not_called()


if __name__ == "__main__":
    unittest.main()
