"""Safely reassign a pending ZIP-first branch without changing archive provenance."""

from pathlib import Path

from .branch_guard import assert_no_unfinished_feature_branches
from .gitutil import (branch_exists, current_branch, head, output, remote_head,
                      worktree_fingerprint)
from .model import Abort, Config, Handoff
from .state import save
from .status import workflow_key
from .zip_resume import verify_applied_zip


def reassign_pending_branch(root: Path, config: Config, handoff: Handoff,
                            state: dict, target: str) -> None:
    """Persist an explicit branch choice only after read-only local/remote guards."""
    key = workflow_key(root, handoff.branch, handoff.patch)
    record = state["workflows"].get(key)
    if (not isinstance(record, dict) or record.get("zip_first") is not True
            or record.get("phase") != "patch_applied"
            or record.get("applied_branch") != config.base
            or record.get("session_id") is not None):
        raise Abort("BRANCH_REASSIGNMENT_UNAVAILABLE: Requires an uncommitted ZIP "
                    "already applied to the base branch, before BRN and session creation")
    if target in {handoff.branch, config.base}:
        raise Abort("BRANCH_REASSIGNMENT_INVALID: Choose a different feature branch")
    if current_branch(root) != config.base:
        raise Abort(f"BRANCH_REASSIGNMENT_DRIFT: Check out {config.base} before reassigning")
    verify_applied_zip(root, config, handoff, state)
    output(["git", "check-ref-format", "--branch", target], root)
    if branch_exists(root, target):
        raise Abort(f"BRANCH_REASSIGNMENT_EXISTS: Feature branch exists locally: {target}")
    if remote_head(root, config, target):
        raise Abort(f"BRANCH_REASSIGNMENT_EXISTS: Feature branch exists on "
                    f"{config.remote}: {target}")
    if head(root) != record.get("before_patch_head"):
        raise Abort("BRANCH_REASSIGNMENT_DRIFT: Base HEAD changed since APL")
    _, paths = worktree_fingerprint(root)
    if not paths or set(paths) != set(record.get("changed_paths", [])):
        raise Abort("BRANCH_REASSIGNMENT_DRIFT: Patch files differ from recorded APL scope")
    original_collision = (branch_exists(root, handoff.branch)
                          or remote_head(root, config, handoff.branch) is not None)
    assert_no_unfinished_feature_branches(
        root, config, target,
        ignore_branch=handoff.branch if original_collision else None)
    if record.get("reassigned_branch") == target:
        print(f"Pending ZIP is already assigned to {target}; no archive replay")
        return

    previous = dict(record)
    record["reassigned_branch"] = target
    record["source_branch"] = handoff.branch
    record["branch"] = target
    try:
        save(config.state_path, state)
    except Exception:
        record.clear()
        record.update(previous)
        raise
    print(f"Pending ZIP reassigned: {handoff.branch} -> {target}")
    print(f"Archive SHA-256 and {len(paths)} recorded changed path(s) preserved; "
          "BRN will not reapply the ZIP")
