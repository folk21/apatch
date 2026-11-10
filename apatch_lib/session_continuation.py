"""Read-only admission for a new ZIP following an already committed feature patch.

The higher-level goal planner will call this guard before selecting an APL.
Existing direct LOOSE followup=true semantics are intentionally unchanged.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from .audit_collectors import local_git, remote_snapshot, safe_text
from .gitutil import status_paths
from .model import Abort, Config, Handoff
from .patch import Archive, inspect
from .patch_history import MAX_HISTORY_BYTES, parse_history
from .session import SESSION_ID, remote_identity
from .state import read_state_snapshot
from .status import workflow_key


_SHA = re.compile(r"^[a-f0-9]{40}$")
_COMMITTED = frozenset({"committed", "pushed", "pr_created"})


@dataclass(frozen=True)
class SessionContinuationEvidence:
    """Verified predecessor facts, not permission to commit or publish."""

    session_id: str
    predecessor_key: str
    predecessor_phase: str
    predecessor_commit: str
    branch: str
    changed_paths: tuple[str, ...]


def _remote_feature_head(root: Path, config: Config, branch: str) -> str | None:
    lines = local_git(root, "ls-remote", "--heads", config.remote,
                      f"refs/heads/{branch}", timeout=config.github_timeout_seconds).splitlines()
    if not lines:
        return None
    if len(lines) != 1:
        raise Abort("Session continuation has ambiguous remote feature refs")
    parts = lines[0].split()
    if (len(parts) != 2 or not _SHA.fullmatch(parts[0])
            or parts[1] != f"refs/heads/{branch}"):
        raise Abort("Session continuation received an invalid remote feature ref")
    return parts[0]


def _ancestor(root: Path, older: str, newer: str) -> bool:
    try:
        local_git(root, "merge-base", "--is-ancestor", older, newer)
    except Abort:
        return False
    return True


def require_session_continuation(
    root: Path, config: Config, handoff: Handoff, session_id: str,
    *, archive: Archive | None = None,
) -> SessionContinuationEvidence:
    """Fail closed before a new ZIP can extend a committed or published session.

    This function reads Git, durable state, history and, for an open PR, bounded
    GitHub evidence. It never writes, locks, selects a handoff, or applies bytes.
    """
    root = root.resolve(strict=True)
    if type(session_id) is not str or not SESSION_ID.fullmatch(session_id):
        raise Abort("Session continuation requires a valid explicit session ID")
    if (handoff.repository != root.name or not handoff.patch_sha256
            or not _SHA.fullmatch(local_git(root, "rev-parse", "HEAD").strip())):
        raise Abort("Session continuation requires a verified repository and ZIP identity")
    branch = local_git(root, "branch", "--show-current").strip()
    if not branch or branch != handoff.branch or branch == config.base:
        raise Abort("Session continuation requires the intended checked-out feature branch")
    current_head = local_git(root, "rev-parse", "HEAD").strip()
    if Path(local_git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:
        raise Abort("Session continuation requires the exact Git repository root")

    state = read_state_snapshot(config.state_path)
    session = state.get("feature_sessions", {}).get(session_id)
    if (not isinstance(session, dict) or session.get("status") != "active"
            or session.get("repository") != str(root)
            or session.get("remote_name") != config.remote
            or session.get("base_branch") != config.base
            or session.get("feature_branch") != branch):
        raise Abort("Session continuation requires one explicitly selected active session")
    url = local_git(root, "remote", "get-url", config.remote).strip()
    if session["remote_identity"] != remote_identity(url):
        raise Abort("Session continuation remote identity differs from the session")
    matches = [item for item in state.get("feature_sessions", {}).values()
               if item["status"] == "active" and item["repository"] == str(root)
               and item["feature_branch"] == branch]
    if len(matches) != 1:
        raise Abort("Session continuation has ambiguous active feature-session owners")

    keys = session["patch_workflow_keys"]
    if not keys:
        raise Abort("Session continuation requires a previously applied session ZIP")
    predecessor_key = keys[-1]
    previous = state["workflows"].get(predecessor_key)
    if not isinstance(previous, dict) or previous.get("phase") not in _COMMITTED:
        raise Abort("Session continuation requires a committed or published predecessor")
    if (previous.get("session_id") != session_id
            or previous.get("repository") != str(root)
            or previous.get("branch") != branch
            or previous.get("applied_branch") != branch
            or previous.get("remote_url") != url):
        raise Abort("Session continuation predecessor identity or remote has drifted")
    commit = previous.get("commit_sha")
    if not isinstance(commit, str) or not _SHA.fullmatch(commit) or commit != current_head:
        raise Abort("Session continuation HEAD differs from the recorded feature commit")
    if previous.get("superseded_by") or previous.get("continued_by"):
        raise Abort("Session continuation cannot infer identity from legacy continuation links")
    if (not isinstance(previous.get("archive_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", previous["archive_sha256"])):
        raise Abort("Session continuation predecessor ZIP digest is missing")
    if not any(
        run.get("workflow_key") == predecessor_key
        and run.get("repository") == str(root)
        and run.get("patch") == previous.get("patch_file")
        and run.get("operation", {}).get("number") == 3
        and run.get("outcome") == "SUCCEEDED"
        and run.get("verified_facts", {}).get("archive_sha256") == previous["archive_sha256"]
        for run in state["operation_runs"]
    ):
        raise Abort("Session continuation predecessor application has no successful journal proof")
    for earlier in session["commit_shas"]:
        if not _ancestor(root, earlier, current_head):
            raise Abort("Session continuation has an unverified historical commit ancestry")
    for key, item in state["workflows"].items():
        if key != predecessor_key and isinstance(item, dict) and item.get("repository") == str(root):
            if (item.get("applied_branch") == branch
                    and item.get("phase") in {"applying", "patch_applied", "verified"}):
                raise Abort("Session continuation has another incomplete feature workflow")

    history_text = safe_text(config.applied_patches_path, MAX_HISTORY_BYTES)
    entries = parse_history(history_text or "")
    latest = entries[-1] if entries else None
    if (latest is None or latest.patch != previous.get("patch_file")
            or latest.planned_branch != branch or latest.real_branch != branch
            or sum(item.patch == latest.patch for item in entries) != 1):
        raise Abort("Session continuation predecessor differs from the last applied ZIP")
    if any(item.patch == handoff.patch for item in entries):
        raise Abort("Session continuation must not replay an already applied ZIP")
    if workflow_key(root, branch, handoff.patch) in state["workflows"]:
        raise Abort("Session continuation new ZIP already has a workflow checkpoint")

    remote_head = _remote_feature_head(root, config, branch)
    if previous["phase"] in {"pushed", "pr_created"}:
        if remote_head != current_head or previous.get("pushed_sha") != current_head:
            raise Abort("Session continuation published revision differs from the live remote")
    elif remote_head is not None and remote_head != current_head:
        historical_pushed = {state["workflows"][key].get("pushed_sha") for key in keys}
        if remote_head not in historical_pushed or not _ancestor(root, remote_head, current_head):
            raise Abort("Session continuation remote branch has unverified ancestry")

    if previous["phase"] == "pr_created":
        heads, prs, complete = remote_snapshot(config, root)
        if not complete or heads.get(branch) != current_head:
            raise Abort("Session continuation cannot verify the live PR head")
        matching = [pr for pr in prs if pr.get("number") == previous.get("pr_number")
                    and pr.get("headRefName") == branch
                    and pr.get("baseRefName") == config.base
                    and pr.get("headRefOid") == current_head
                    and pr.get("state") == "OPEN"]
        if len(matching) != 1:
            raise Abort("Session continuation has no unique matching open PR revision")

    archive = archive or inspect(config, handoff, root)
    if archive.sha256 != handoff.patch_sha256 or archive.embedded_handoff is None:
        raise Abort("Session continuation requires the exact self-contained new ZIP")
    changed = status_paths(root)
    collisions = sorted(set(changed) & (set(archive.changed) | set(handoff.delete_paths)))
    if collisions:
        raise Abort("Session continuation overlaps locally modified paths: " + ", ".join(collisions))
    return SessionContinuationEvidence(session_id, predecessor_key, previous["phase"],
                                       current_head, branch, tuple(sorted(changed)))

def require_committed_loose_followup(
    root: Path, config: Config, handoff: Handoff, state: dict, *,
    archive: Archive | None = None,
) -> str:
    """Verify a clean, committed legacy LOOSE predecessor without adopting a session.

    Applied-history order selects the predecessor, never dictionary insertion order.
    This is an explicit APL-only guard and does not authorize guarded goals or
    future Git publication.
    """
    root = root.resolve(strict=True)
    branch = local_git(root, "branch", "--show-current").strip()
    current_head = local_git(root, "rev-parse", "HEAD").strip()
    if (handoff.repository != root.name or not handoff.patch_sha256
            or branch != handoff.branch or branch == config.base
            or not _SHA.fullmatch(current_head)
            or Path(local_git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root):
        raise Abort("Committed follow-up requires the exact repository and checked-out feature branch")
    if status_paths(root):
        raise Abort("Committed follow-up requires a clean worktree and index")
    for session in state.get("feature_sessions", {}).values():
        if (session.get("status") == "active" and session.get("repository") == str(root)
                and session.get("feature_branch") == branch):
            raise Abort("Committed follow-up is linked to an active feature session; use a guarded goal")

    history_text = safe_text(config.applied_patches_path, MAX_HISTORY_BYTES)
    entries = parse_history(history_text or "")
    latest = entries[-1] if entries else None
    if (latest is None or latest.real_branch != branch
            or any(item.patch == handoff.patch for item in entries)
            or sum(item.patch == latest.patch for item in entries) != 1):
        raise Abort("Committed follow-up requires a unique last applied ZIP on the feature branch")
    previous_key = workflow_key(root, latest.planned_branch, latest.patch)
    previous = state["workflows"].get(previous_key)
    if (not isinstance(previous, dict) or previous.get("phase") != "committed"
            or previous.get("patch_file") != latest.patch
            or previous.get("repository") != str(root)
            or previous.get("branch") != branch
            or (latest.planned_branch != branch and
                (previous.get("source_branch") != latest.planned_branch
                 or previous.get("reassigned_branch") != branch))
            or previous.get("applied_branch") != branch
            or previous.get("commit_sha") != current_head
            or previous.get("superseded_by")
            or previous.get("continued_by")
            or previous.get("session_id") is not None
            or not isinstance(previous.get("archive_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", previous["archive_sha256"])):
        raise Abort("Committed follow-up has no uniquely verified latest commit checkpoint")
    if workflow_key(root, branch, handoff.patch) in state["workflows"]:
        raise Abort("Committed follow-up ZIP already has a workflow checkpoint")
    if any(isinstance(record, dict) and key != previous_key
           and record.get("repository") == str(root)
           and record.get("applied_branch") == branch
           and record.get("phase") in {"applying", "patch_applied", "verified"}
           for key, record in state["workflows"].items()):
        raise Abort("Committed follow-up has an unresolved earlier feature workflow")
    if not any(
        run.get("workflow_key") == previous_key
        and run.get("repository") == str(root)
        and run.get("patch") == latest.patch
        and run.get("operation", {}).get("number") in (2, 3)
        and run.get("outcome") == "SUCCEEDED"
        and run.get("verified_facts", {}).get("archive_sha256") == previous["archive_sha256"]
        for run in state.get("operation_runs", [])
    ):
        raise Abort("Committed follow-up predecessor has no successful application journal proof")
    url = local_git(root, "remote", "get-url", config.remote).strip()
    if previous.get("remote_url") != url:
        raise Abort("Committed follow-up Git remote identity has changed")
    if not _ancestor(root, f"refs/heads/{config.base}", current_head):
        raise Abort("Committed follow-up HEAD is not a descendant of the configured local base")
    remote_sha = _remote_feature_head(root, config, branch)
    if remote_sha is not None and remote_sha != current_head:
        historical_pushed = {record.get("pushed_sha") for record in state["workflows"].values()
                             if isinstance(record, dict)
                             and record.get("repository") == str(root)
                             and record.get("applied_branch") == branch}
        if remote_sha not in historical_pushed or not _ancestor(root, remote_sha, current_head):
            raise Abort("Committed follow-up remote branch has unverified drift")
    archive = archive or inspect(config, handoff, root)
    if archive.embedded_handoff is None or archive.sha256 != handoff.patch_sha256:
        raise Abort("Committed follow-up requires the exact self-contained ZIP")
    return previous_key

