"""Check-boundary policy for explicit, incremental LOOSE publication.

Only the configured boundary can be relaxed. The final merge remains protected
whenever any earlier feature commit was made without canonical verification.
"""

from ..mo_feature_sessions.commit_scope import policy_fingerprint
from ..gitutil import current_branch, head, status_paths, worktree_fingerprint
from ..model import Abort

BOUNDARIES = ("CMT", "PSH", "PR", "MRG")


def _verified_dirty(workflow):
    fingerprint, paths = worktree_fingerprint(workflow.root)
    record = workflow.record
    return (bool(paths) and record.get("verified_fingerprint") == fingerprint
            and record.get("verified_head") == head(workflow.root)
            and record.get("verified_branch") == current_branch(workflow.root)
            and record.get("verified_policy_fingerprint") ==
            policy_fingerprint(workflow.root, workflow.config))


def _verified_committed(workflow):
    return (not status_paths(workflow.root)
            and workflow.record.get("verified_commit") == head(workflow.root)
            and workflow.record.get("verified_branch") == current_branch(workflow.root)
            and workflow.record.get("verified_policy_fingerprint") ==
            policy_fingerprint(workflow.root, workflow.config))


def _unverified_history(workflow):
    repository = str(workflow.root.resolve())
    branch = current_branch(workflow.root)
    return any(isinstance(record, dict)
               and record.get("repository") == repository
               and record.get("applied_branch") == branch
               and (record.get("unchecked_commit_sha") or record.get("unchecked_pending"))
               for record in workflow.state.get("workflows", {}).values())


def require_boundary(workflow, action: str) -> None:
    """Reject the configured gate before any Git/GitHub mutation.

    Guarded goals and STRICT retain their stronger canonical-check contracts.
    FORCE retains its supervised recovery path except for a pending merge gate.
    """
    if action not in BOUNDARIES:
        return
    threshold = workflow.config.disabled_without_chk
    if not workflow.loose and not workflow.force:
        if action == "MRG" and _unverified_history(workflow) and not _verified_committed(workflow):
            raise Abort("CHECK_GATE_MRG: Earlier unchecked commits require CHK on the "
                        "final clean feature HEAD before merge")
        return
    if workflow.force and action == "CMT":
        return
    if action == "MRG" and (_unverified_history(workflow) or threshold == "MRG"):
        if not _verified_committed(workflow):
            raise Abort("CHECK_GATE_MRG: Run CHK on the final clean feature HEAD "
                        "after the last commit and push, before merge")
        return
    if threshold != action:
        if action == "CMT" and workflow.loose and threshold != "CMT" and not _verified_dirty(workflow):
            branch = current_branch(workflow.root)
            if (branch != workflow.handoff.branch or branch == workflow.config.base
                    or workflow.phase in {"new", "applying", "merged", "synced"}
                    or not workflow.record.get("archive_sha256")):
                raise Abort("CHECK_GATE_UNCHECKED_COMMIT: An unchecked commit requires "
                            "a verified applied ZIP on its named feature branch")
        return
    if action == "CMT":
        if workflow.record.get("phase") not in {"verified", "patch_applied"}:
            raise Abort("CHECK_GATE_CMT: Apply the patch and run CHK before committing")
        if not _verified_dirty(workflow):
            raise Abort("CHECK_GATE_CMT: Run CHK on the exact current changed bytes "
                        "before committing")
    elif not _verified_committed(workflow):
        raise Abort(f"CHECK_GATE_{action}: Run CHK on the final committed HEAD "
                    f"before {action}")


def record_commit(workflow, committed_sha: str, *, was_verified: bool) -> None:
    """Retain an irreversible history marker until a final checked merge."""
    if not was_verified:
        workflow.record["unchecked_commit_sha"] = committed_sha
        workflow.record["unchecked_pending"] = True
    checked_policy = workflow.record.get("verified_policy_fingerprint") if was_verified else None
    checked_branch = workflow.record.get("verified_branch") if was_verified else None
    for field in ("verified_fingerprint", "verified_head", "verified_branch",
                  "verified_commit", "verified_policy_fingerprint", "guarded_verification",
                  "code_review"):
        workflow.record.pop(field, None)
    if was_verified and checked_policy and checked_branch:
        # The caller verified the exact staged path set and committed Git tree.
        workflow.record.update(verified_commit=committed_sha,
                               verified_branch=checked_branch,
                               verified_policy_fingerprint=checked_policy)
