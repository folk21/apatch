"""Execute configured canonical checks and record exact worktree evidence."""

from apatch_lib.mo_git.repository import head, require_branch
from apatch_lib.mo_git.commands import run
from ..mo_core.enums import WorkflowPhase
from apatch_lib.mo_core.api import Abort


def run_checks(workflow) -> bool:
    """Run CHK without weakening branch, patch, or changed-byte gates."""
    if workflow.phase not in {WorkflowPhase.PATCH_APPLIED, WorkflowPhase.VERIFIED}:
        raise Abort("There is no uncommitted applied patch to verify")
    workflow.record.pop("code_review", None)
    require_branch(workflow.root, workflow.applied_branch)
    workflow.assert_remote_unchanged()
    if head(workflow.root) != workflow.record.get("before_patch_head"):
        raise Abort("HEAD drifted after patch application")
    workflow.assert_patch_identity()
    before, _ = workflow.assert_expected_paths()
    run(["git", "diff", "--check"], workflow.root)
    if not workflow.config.checks:
        raise Abort("No project verification commands configured")
    for command in workflow.config.checks:
        run(list(command), workflow.root, stream_output=True,
            timeout=workflow.config.check_timeout_seconds,
            idle_timeout=workflow.config.check_idle_timeout_seconds)
    after, _ = workflow.assert_expected_paths()
    if before != after:
        workflow.record["phase"] = WorkflowPhase.PATCH_APPLIED.value
        workflow.persist()
        raise Abort("Tests changed repository files; verification invalidated")
    workflow.record.update(phase="verified", verified_fingerprint=after)
    workflow.persist()
    print("Canonical checks passed for the current changed bytes. Review the diff before commit.")
    return True
