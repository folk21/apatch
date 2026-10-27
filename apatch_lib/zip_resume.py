"""Prove an explicit ZIP was already applied without replaying its contents."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .core.contracts import StateDocument
from .gitutil import current_branch, head, output, worktree_fingerprint
from .model import Abort, Config, Handoff
from .patch_history import AppliedPatchHistory
from .status import workflow_key


APPLIED_PHASES = frozenset({
    "patch_applied", "verified", "committed", "pushed", "pr_created", "merged", "synced",
})
UNCOMMITTED_PHASES = frozenset({"patch_applied", "verified"})


@dataclass(frozen=True)
class AppliedZipEvidence:
    patch: str
    phase: str
    branch: str
    pending_branch: bool


def handoff_signature(handoff: Handoff) -> str:
    """Keep the persisted handoff identity compatible with existing checkpoints."""
    payload = {
        "repository": handoff.repository, "branch": handoff.branch,
        "patch": handoff.patch, "message": handoff.message,
        "base": handoff.base_commit, "digest": handoff.patch_sha256,
        "deletes": handoff.delete_paths,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def verify_applied_zip(
    root: Path, config: Config, handoff: Handoff, state: StateDocument,
) -> AppliedZipEvidence:
    """Require matching checkpoint, latest journal entry, APL run and live local Git."""
    reason = ("Explicit ZIP resume is not proven; inspect op=STS and op=AUD. "
              "Do not reapply a previously recorded ZIP.")
    key = workflow_key(root, handoff.branch, handoff.patch)
    record = state["workflows"].get(key)
    if not isinstance(record, dict) or record.get("phase") not in APPLIED_PHASES:
        raise Abort(f"{reason} No completed application checkpoint for {handoff.patch}.")
    if (record.get("repository") != str(root.resolve())
            or record.get("branch") != handoff.branch
            or record.get("patch_file") != handoff.patch
            or record.get("handoff_signature") != handoff_signature(handoff)
            or record.get("archive_sha256") != handoff.patch_sha256):
        raise Abort(f"{reason} Selected ZIP identity or digest conflicts with the checkpoint.")
    if record.get("superseded_by") or record.get("continued_by"):
        raise Abort(f"{reason} The recorded patch has a newer continuation.")
    if config.applied_patches_path.is_symlink():
        raise Abort(f"{reason} Applied-history source is a symlink.")
    with_history = AppliedPatchHistory(config.applied_patches_path)
    matches = [entry for entry in with_history.entries if entry.patch == handoff.patch]
    if (len(matches) != 1 or not with_history.entries
            or with_history.entries[-1].patch != handoff.patch):
        raise Abort(f"{reason} ZIP is missing, duplicated or not last in applied history.")
    entry = matches[0]
    if (entry.date is None or entry.planned_branch != handoff.branch
            or entry.real_branch != record.get("applied_branch")):
        raise Abort(f"{reason} Applied-history branch or structured identity differs.")
    runs = state.get("operation_runs", [])
    applied = any(
        run.get("repository") == str(root.resolve())
        and run.get("workflow_key") == key
        and run.get("patch") == handoff.patch
        and run.get("operation", {}).get("number") == 3
        and run.get("outcome") == "SUCCEEDED"
        and run.get("verified_facts", {}).get("archive_sha256") == handoff.patch_sha256
        for run in runs
    )
    if not applied:
        raise Abort(f"{reason} A matching successful APL journal run is missing.")

    phase = record["phase"]
    pending_branch = (record.get("zip_first") is True
                      and phase == "patch_applied"
                      and record.get("applied_branch") == config.base)
    branch = current_branch(root)
    if branch != (config.base if pending_branch else handoff.branch):
        raise Abort(f"{reason} Current branch {branch or 'DETACHED'} does not match the checkpoint.")
    remote_url = output(["git", "remote", "get-url", config.remote], root)
    if not record.get("remote_url") or remote_url != record["remote_url"]:
        raise Abort(f"{reason} Configured remote identity has changed.")
    if phase in UNCOMMITTED_PHASES:
        if head(root) != record.get("before_patch_head"):
            raise Abort(f"{reason} HEAD changed since the uncommitted application.")
        _, paths = worktree_fingerprint(root)
        expected = record.get("changed_paths")
        if not isinstance(expected, list) or not expected or not set(expected).issubset(paths):
            raise Abort(f"{reason} Recorded patch paths are missing from the worktree.")
    elif phase != "synced" and head(root) != record.get("commit_sha"):
        raise Abort(f"{reason} The local commit differs from the recorded revision.")

    return AppliedZipEvidence(handoff.patch, phase, branch, pending_branch)
