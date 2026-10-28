"""Evidence-bound commit scope for a future local goal planner.

This module is internal. A caller must supply an active session and explicitly
accepted manual paths; skipApproves never expands the allowed set.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .gitutil import current_branch, head, output, status_paths, worktree_fingerprint
from .model import Abort, safe_relative
from .session import remote_identity, validate_feature_sessions


class WaitingForUser(Abort):
    """A manual path requires an explicit, path-specific authorization."""


class NeedsVerification(Abort):
    """The canonical check evidence does not match the current bytes/policy."""


@dataclass(frozen=True)
class CommitScope:
    """Exact observed changed paths plus their authorization provenance."""

    session_id: str
    branch: str
    head: str
    fingerprint: str
    contents_fingerprint: str
    policy_fingerprint: str
    paths: tuple[str, ...]
    accepted_manual: tuple[str, ...]


def changed_contents_fingerprint(root: Path, paths) -> str:
    """Hash changed working-tree bytes and modes independently of Git staging."""
    digest = hashlib.sha256()
    for name in sorted(paths):
        safe_relative(name)
        file = root / name
        digest.update(os.fsencode(name) + b"\x00")
        if file.is_symlink():
            digest.update(b"L" + os.fsencode(os.readlink(file)) + b"\x00")
        elif file.is_file():
            digest.update(b"F1" if file.stat().st_mode & 0o111 else b"F0")
            with file.open("rb") as stream:
                for part in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(part)
        elif not file.exists() and not file.is_symlink():
            digest.update(b"D")
        else:
            raise Abort(f"Unsupported commit path: {name}")
        digest.update(b"\x00")
    return digest.hexdigest()


def policy_fingerprint(root: Path, config) -> str:
    """Bind checks to both the effective settings and exact project policy bytes."""
    file = root / ".apatch" / "config.yaml"
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 65536:
        raise Abort("Cannot verify the current project checks config")
    policy = {
        "checks": config.checks,
        "timeout": config.check_timeout_seconds,
        "idle_timeout": config.check_idle_timeout_seconds,
        "remote": config.remote,
        "base": config.base,
        "require_checks": config.require_checks,
        "require_approval": config.require_approval,
        "raw_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def _owned_paths(workflow, session_id: str) -> tuple[set[str], set[str]]:
    """Use only applied, uncommitted, session-linked ZIP footprints as ownership."""
    state = workflow.state
    validate_feature_sessions(state.get("feature_sessions", {}), state["workflows"])
    session = state.get("feature_sessions", {}).get(session_id)
    if session is None or session["status"] != "active":
        raise Abort("Guarded commit requires an active feature session")
    root = workflow.root.resolve()
    branch = current_branch(root)
    if (session["repository"] != str(root) or branch != session["feature_branch"]
            or branch == workflow.config.base or workflow.handoff.branch != branch
            or session["remote_name"] != workflow.config.remote
            or session["base_branch"] != workflow.config.base
            or session["remote_identity"] != remote_identity(output(
                ["git", "remote", "get-url", workflow.config.remote], root))):
        raise Abort("Guarded commit branch, base, or remote identity differs")
    if not session["patch_workflow_keys"] or session["patch_workflow_keys"][-1] != workflow.key:
        raise Abort("Guarded commit requires the latest selected session patch")
    current_head = head(root)
    owned = set()
    preexisting_staged = set()
    for key in session["patch_workflow_keys"]:
        record = state["workflows"][key]
        if record.get("phase") not in {"patch_applied", "verified"}:
            continue
        if (record.get("session_id") != session_id
                or record.get("applied_branch") != branch
                or record.get("before_patch_head") != current_head):
            raise Abort("Guarded commit has an incompatible pending patch revision")
        footprint = record.get("patch_footprint")
        if (type(footprint) is not list or not footprint
                or any(type(item) is not str or safe_relative(item) != item
                       for item in footprint)):
            raise WaitingForUser(
                "WAITING_FOR_USER: Pending patch ownership was not recorded; use "
                "supervised LOOSE CMT or a later explicitly reviewed migration")
        staged = record.get("preexisting_staged_paths")
        if type(staged) is not list:
            raise WaitingForUser(
                "WAITING_FOR_USER: Pre-application staged paths were not classified")
        # Earlier session-owned ZIP changes may already be staged by guarded CHK.
        # Only newly introduced staged paths need separate manual acceptance.
        preexisting_staged.update(set(staged) - owned)
        owned.update(footprint)
    if not owned or workflow.record.get("phase") not in {"patch_applied", "verified"}:
        raise Abort("Guarded commit requires an applied, uncommitted session patch")
    for key, record in state["workflows"].items():
        if (key not in session["patch_workflow_keys"] and isinstance(record, dict)
                and record.get("repository") == str(root)
                and record.get("applied_branch") == branch
                and record.get("phase") in {"applying", "patch_applied", "verified"}):
            raise WaitingForUser(
                "WAITING_FOR_USER: Another unclassified patch is pending on this branch")
    return owned, preexisting_staged


def inspect_commit_scope(workflow, session_id: str, *,
                         accepted_manual_paths=()) -> CommitScope:
    """Fail closed if any changed path lacks exact ZIP/manual authorization."""
    if not workflow.loose or workflow.force:
        raise Abort("Guarded commit is available only for internal LOOSE goals")
    root = workflow.root.resolve()
    owned, preexisting_staged = _owned_paths(workflow, session_id)
    manual = tuple(accepted_manual_paths)
    if len(set(manual)) != len(manual) or any(type(path) is not str for path in manual):
        raise Abort("Manual commit path acceptance must contain distinct paths")
    for path in manual:
        safe_relative(path)
    fingerprint, paths = worktree_fingerprint(root)
    if not paths:
        raise NeedsVerification("NEEDS_VERIFICATION: There are no changed bytes to commit")
    if any("R" in code or "C" in code or "U" in code or code == "!!"
           for code in paths.values()):
        raise WaitingForUser(
            "WAITING_FOR_USER: Rename/copy/conflict statuses require supervised review")
    manual_set = set(manual)
    if manual_set - set(paths):
        raise Abort("Accepted manual paths must exist in the current changed-path inventory")
    unclassified = set(paths) - ((owned - preexisting_staged) | manual_set)
    if unclassified:
        preview = ", ".join(sorted(unclassified)[:8])
        raise WaitingForUser(
            f"WAITING_FOR_USER: Unclassified commit paths: {preview}; "
            "explicitly accept each path or use supervised LOOSE CMT")
    if (set(paths) & preexisting_staged) - manual_set:
        raise WaitingForUser("WAITING_FOR_USER: Pre-existing staged files need explicit acceptance")
    return CommitScope(session_id, current_branch(root), head(root), fingerprint,
                       changed_contents_fingerprint(root, paths),
                       policy_fingerprint(root, workflow.config),
                       tuple(sorted(paths)), tuple(sorted(manual)))


def assert_scope_unchanged(workflow, scope: CommitScope) -> CommitScope:
    """Recheck every guard immediately before a planned Git mutation."""
    fresh = inspect_commit_scope(workflow, scope.session_id,
                                 accepted_manual_paths=scope.accepted_manual)
    if fresh != scope:
        raise NeedsVerification(
            "NEEDS_VERIFICATION: Branch, HEAD, Git bytes, path scope or check policy changed")
    return fresh
