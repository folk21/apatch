"""Read-only feature-session evidence reconciliation for a future goal planner.

This module classifies observations. It never authorizes a lifecycle action or
changes the existing STS, AUD, explicit op, or opSeq admission rules.
"""

import os
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .audit_collectors import local_git, remote_snapshot
from .model import Abort, Config, Handoff
from .session import remote_identity
from .state import read_state_snapshot
from .status import workflow_key
from .zip_resume import APPLIED_PHASES, verify_applied_zip


_COMMITTED_PHASES = frozenset({"committed", "pushed", "pr_created", "merged", "synced"})
_REMOTE_PHASES = frozenset({"pushed", "pr_created", "merged", "synced"})
_REVISION = re.compile(r"^[a-f0-9]{40}$")


class Scenario(str, Enum):
    """Potential context; none of these values grants permission to mutate."""

    NEW_BASE = "NEW_BASE"
    ACTIVE_UNCOMMITTED = "ACTIVE_UNCOMMITTED"
    COMMITTED = "COMMITTED"
    PUSHED_OR_OPEN_PR = "PUSHED_OR_OPEN_PR"
    ALREADY_APPLIED_ZIP = "ALREADY_APPLIED_ZIP"
    MISSING_CHECKS = "MISSING_CHECKS"
    MANUAL_DRIFT = "MANUAL_DRIFT"
    UNKNOWN_REMOTE = "UNKNOWN_REMOTE"
    AMBIGUOUS = "AMBIGUOUS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class GuardFinding:
    code: str
    evidence: str
    detail: str


@dataclass(frozen=True)
class ContextReport:
    """Immutable diagnostic observations without an executable action plan."""

    scenario: Scenario
    repository: Path
    branch: str
    head: str
    changed_paths: tuple[str, ...]
    session_id: str | None
    selected_patch: str | None
    remote_coverage: str
    findings: tuple[GuardFinding, ...]


@dataclass(frozen=True)
class GuardedCommitReadiness:
    """Read-only decision for the internal FS-04 commit gate."""

    status: str
    detail: str
    paths: tuple[str, ...] = ()


def inspect_guarded_commit_readiness(workflow, session_id: str, *,
                                     accepted_manual_paths=()) -> GuardedCommitReadiness:
    """Classify exact scope/evidence without staging, locking or persisting."""
    from .commit_scope import (NeedsVerification, WaitingForUser,
                               inspect_commit_scope)

    try:
        scope = inspect_commit_scope(workflow, session_id,
                                     accepted_manual_paths=accepted_manual_paths)
    except WaitingForUser as exc:
        return GuardedCommitReadiness("WAITING_FOR_USER", str(exc))
    except NeedsVerification as exc:
        return GuardedCommitReadiness("NEEDS_VERIFICATION", str(exc))
    except Abort as exc:
        return GuardedCommitReadiness("BLOCKED", str(exc))

    record = workflow.record
    expected = {
        "session_id": scope.session_id, "branch": scope.branch, "head": scope.head,
        "fingerprint": scope.fingerprint, "policy_fingerprint": scope.policy_fingerprint,
        "paths": list(scope.paths), "accepted_manual": list(scope.accepted_manual),
    }
    verified = record.get("guarded_verification")
    if (verified != expected or record.get("verified_fingerprint") != scope.fingerprint
            or record.get("verified_head") != scope.head
            or record.get("verified_branch") != scope.branch):
        return GuardedCommitReadiness(
            "NEEDS_VERIFICATION", "Stage only authorized paths and run canonical checks",
            scope.paths)
    return GuardedCommitReadiness(
        "READY", "The recorded guarded CHK matches current bytes and policy",
        scope.paths)


def _changed_paths(root: Path) -> tuple[str, ...]:
    raw = local_git(root, "-c", "core.quotePath=false", "status", "--porcelain=v1",
                    "--untracked-files=all", "-z")
    records = raw.split("\0")
    names = []
    index = 0
    while index < len(records) and records[index]:
        record = records[index]
        if len(record) < 4 or record[2] != " ":
            raise Abort("Unrecognized local Git status record")
        names.append(record[3:])
        if "R" in record[:2] or "C" in record[:2]:
            index += 1
        index += 1
    return tuple(sorted(names))


def _missing_check_commands(root: Path, checks: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    """Inspect directly executable commands without running arbitrary checks."""
    missing = []
    for args in checks:
        if not args:
            missing.append("<empty check command>")
            continue
        executable = args[0]
        if "/" in executable:
            path = Path(executable)
            candidate = path if path.is_absolute() else root / path
            available = candidate.is_file() and os.access(candidate, os.X_OK)
        else:
            available = shutil.which(executable) is not None
        if not available:
            missing.append(executable)
            continue
        if executable in {"sh", "bash", "python", "python3"} and len(args) > 1:
            script = args[1]
            if script.startswith("-"):
                continue
            path = Path(script)
            candidate = path if path.is_absolute() else root / path
            if not candidate.is_file():
                missing.append(script)
    return tuple(missing)


def _session_candidates(state: dict, root: Path, branch: str) -> list[dict]:
    repository = str(root.resolve())
    return [item for item in state.get("feature_sessions", {}).values()
            if item["repository"] == repository and item["feature_branch"] == branch
            and item["status"] == "active"]


def inspect_context(
    root: Path, config: Config, *, handoff: Handoff | None = None,
    session_id: str | None = None, verify_remote: bool = False,
) -> ContextReport:
    """Inspect one repository once; never lock, persist, fetch, or repair state.

    Remote verification is an explicit opt-in and consists only of bounded
    read-only queries. Unknown or conflicting facts remain visible in findings.
    """
    root = root.resolve(strict=True)
    repository = local_git(root, "rev-parse", "--show-toplevel").strip()
    if Path(repository).resolve() != root:
        raise Abort(f"Context inspection requires the Git repository root: {root}")
    branch = local_git(root, "branch", "--show-current").strip()
    head = local_git(root, "rev-parse", "HEAD").strip()
    paths = _changed_paths(root)
    state = read_state_snapshot(config.state_path)
    selected_patch = handoff.patch if handoff else None
    findings: list[GuardFinding] = []
    remote_coverage = "UNKNOWN"

    def report(scenario: Scenario, session: dict | None = None) -> ContextReport:
        return ContextReport(scenario, root, branch, head, paths,
                             session["session_id"] if session else None,
                             selected_patch, remote_coverage, tuple(findings))

    def flag(code: str, evidence: str, detail: str) -> None:
        findings.append(GuardFinding(code, evidence, detail))

    if not branch:
        flag("DETACHED_HEAD", "CONFLICT", "A detached checkout cannot identify a feature session")
        return report(Scenario.MANUAL_DRIFT)
    if handoff and handoff.repository != root.name:
        flag("WRONG_REPOSITORY", "CONFLICT", "The selected ZIP names another repository")
        return report(Scenario.BLOCKED)
    if not config.checks:
        flag("MISSING_CHECKS", "CONFLICT", "No project verification commands are configured")
        return report(Scenario.MISSING_CHECKS)
    missing = _missing_check_commands(root, config.checks)
    if missing:
        flag("MISSING_CHECK_EXECUTABLE", "CONFLICT", ", ".join(missing))
        return report(Scenario.MISSING_CHECKS)

    try:
        remote_url = local_git(root, "remote", "get-url", config.remote).strip()
    except Abort:
        flag("CONFIGURED_REMOTE_UNAVAILABLE", "UNKNOWN", "Configured Git remote cannot be inspected")
        return report(Scenario.UNKNOWN_REMOTE)
    observed_remote_id = remote_identity(remote_url)
    selected_record = (state["workflows"].get(workflow_key(root, handoff.branch, handoff.patch))
                       if handoff else None)
    intended_branch = (selected_record.get("reassigned_branch", handoff.branch)
                       if handoff and isinstance(selected_record, dict)
                       else handoff.branch if handoff else branch)
    candidates = _session_candidates(state, root, intended_branch)
    if session_id is not None:
        candidates = [item for item in candidates if item["session_id"] == session_id]
        if not candidates:
            flag("SESSION_MISMATCH", "CONFLICT", "Selected session is absent, terminal or belongs to another branch")
            return report(Scenario.BLOCKED)
    if len(candidates) > 1:
        flag("MULTIPLE_SESSIONS", "CONFLICT", "Several active sessions match this repository and feature branch")
        return report(Scenario.AMBIGUOUS)
    session = candidates[0] if candidates else None
    if session and (session["remote_name"] != config.remote
                    or session["remote_identity"] != observed_remote_id
                    or session["base_branch"] != config.base):
        flag("SESSION_REMOTE_DRIFT", "CONFLICT", "Stored session remote or base identity differs from current configuration")
        return report(Scenario.MANUAL_DRIFT, session)

    record = None
    if handoff is not None:
        record = state["workflows"].get(workflow_key(root, handoff.branch, handoff.patch))
        if record and record.get("phase") in APPLIED_PHASES:
            if record.get("superseded_by") or record.get("continued_by"):
                flag("HISTORICAL_CONTINUATION", "RECORDED",
                     "Legacy continuation linkage is not proof of changed or removed patch bytes")
                return report(Scenario.AMBIGUOUS, session)
            try:
                verify_applied_zip(root, config, handoff, state)
            except Abort:
                flag("ZIP_APPLICATION_UNVERIFIED", "CONFLICT", "Selected ZIP fails checkpoint, applied-history or live Git checks")
                return report(Scenario.BLOCKED, session)
            if session and record.get("session_id") not in (None, session["session_id"]):
                flag("ZIP_SESSION_MISMATCH", "CONFLICT", "Applied ZIP belongs to another feature session")
                return report(Scenario.BLOCKED, session)
            flag("APPLIED_ZIP", "VERIFIED", "Selected ZIP is the latest verified applied patch; no replay is necessary")
            return report(Scenario.ALREADY_APPLIED_ZIP, session)
        if record is not None:
            flag("ZIP_WORKFLOW_INCOMPLETE", "CONFLICT", "Selected ZIP already has a conflicting or incomplete workflow")
            return report(Scenario.BLOCKED, session)

    if session and session["patch_workflow_keys"]:
        key = session["patch_workflow_keys"][-1]
        record = state["workflows"].get(key)
    elif not session:
        local_records = [item for item in state["workflows"].values()
                         if item.get("repository") == str(root)
                         and item.get("applied_branch", item.get("branch")) == branch
                         and item.get("phase") in APPLIED_PHASES]
        if len(local_records) > 1:
            flag("AMBIGUOUS_WORKFLOW", "CONFLICT", "Several patch workflows match the current branch")
            return report(Scenario.AMBIGUOUS, session)
        record = local_records[0] if local_records else None

    if record and record.get("phase") in _COMMITTED_PHASES:
        commit = record.get("commit_sha")
        if not isinstance(commit, str) or not _REVISION.fullmatch(commit) or commit != head:
            flag("COMMIT_DRIFT", "CONFLICT", "Current HEAD differs from the recorded feature commit")
            return report(Scenario.MANUAL_DRIFT, session)
        if branch != record.get("applied_branch", record.get("branch")):
            flag("FEATURE_BRANCH_DRIFT", "CONFLICT", "Committed patch is not on its recorded branch")
            return report(Scenario.MANUAL_DRIFT, session)
        if record["phase"] not in _REMOTE_PHASES:
            flag("LOCAL_COMMIT", "VERIFIED", "Recorded commit matches current local HEAD; publication is unverified")
            return report(Scenario.COMMITTED, session)
        if not verify_remote:
            flag("REMOTE_NOT_QUERIED", "UNKNOWN", "Pushed/PR state requires fresh remote verification")
            return report(Scenario.UNKNOWN_REMOTE, session)
        try:
            heads, prs, complete = remote_snapshot(config, root)
        except (Abort, ValueError, KeyError, TypeError):
            flag("REMOTE_UNAVAILABLE", "UNKNOWN", "Read-only remote branch/PR inspection did not complete")
            return report(Scenario.UNKNOWN_REMOTE, session)
        if not complete:
            flag("PR_COVERAGE_INCOMPLETE", "UNKNOWN", "GitHub PR listing reached its configured bound")
            return report(Scenario.UNKNOWN_REMOTE, session)
        remote_coverage = "VERIFIED"
        if heads.get(branch) != head:
            flag("PUSHED_HEAD_DRIFT", "CONFLICT", "Remote branch no longer matches the recorded local feature commit")
            return report(Scenario.MANUAL_DRIFT, session)
        if record["phase"] != "pushed":
            expected_pr_state = "MERGED" if record["phase"] in {"merged", "synced"} else "OPEN"
            matching = [pr for pr in prs if pr.get("headRefName") == branch
                        and pr.get("baseRefName") == config.base and pr.get("headRefOid") == head
                        and pr.get("state") == expected_pr_state]
            if len(matching) != 1 or matching[0].get("number") != record.get("pr_number"):
                flag("PR_REVISION_UNVERIFIED", "CONFLICT", "No unique live PR matches the recorded number, base and feature commit")
                return report(Scenario.BLOCKED, session)
        flag("PUBLISHED_REVISION", "VERIFIED", "Remote branch matches local HEAD; required PR identity was checked")
        return report(Scenario.PUSHED_OR_OPEN_PR, session)

    if record and record.get("phase") in {"patch_applied", "verified"}:
        if branch != record.get("applied_branch", record.get("branch")) or head != record.get("before_patch_head"):
            flag("UNCOMMITTED_HEAD_DRIFT", "CONFLICT", "Uncommitted patch HEAD or branch does not match its checkpoint")
            return report(Scenario.MANUAL_DRIFT, session)
        if not paths:
            flag("UNCOMMITTED_BYTES_MISSING", "CONFLICT", "Recorded uncommitted patch has no visible working-tree changes")
            return report(Scenario.MANUAL_DRIFT, session)
        flag("UNCOMMITTED_PATCH", "RECORDED", "Current changes and HEAD are compatible with an unfinished patch; exact scope is not authorized")
        return report(Scenario.ACTIVE_UNCOMMITTED, session)

    if branch == config.base and not paths:
        if verify_remote:
            try:
                output = local_git(root, "ls-remote", "--heads", config.remote,
                                   f"refs/heads/{config.base}", timeout=config.github_timeout_seconds)
            except Abort:
                flag("BASE_REMOTE_UNKNOWN", "UNKNOWN", "Cannot verify the configured remote base HEAD")
                return report(Scenario.UNKNOWN_REMOTE, session)
            remote_heads = [line.split()[0] for line in output.splitlines()
                            if line.endswith(f"refs/heads/{config.base}")]
            if len(remote_heads) != 1 or remote_heads[0] != head:
                flag("BASE_NOT_SYNCHRONIZED", "CONFLICT", "Local base is not proven equal to its remote branch")
                return report(Scenario.MANUAL_DRIFT, session)
            remote_coverage = "VERIFIED"
        else:
            flag("BASE_REMOTE_UNVERIFIED", "UNKNOWN", "Local base is clean; remote synchronization has not been checked")
        return report(Scenario.NEW_BASE, session)

    if branch == config.base and paths:
        flag("DIRTY_BASE", "CONFLICT", "Base checkout contains unclassified worktree changes")
        return report(Scenario.MANUAL_DRIFT, session)

    flag("NO_UNIQUE_CONTEXT", "UNKNOWN", "Observed checkout lacks a uniquely verified current feature workflow")
    return report(Scenario.AMBIGUOUS, session)
