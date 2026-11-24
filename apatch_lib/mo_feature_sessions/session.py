"""Feature-session lifecycle updates using validated, caller-owned state."""

import uuid
from pathlib import Path

from ..model import Abort
from ..mo_storage.operation_events import RunOutcome, utc_now
from .validation import (SESSION_ID, SHA, REMOTE_ID, MAX_SESSIONS, MAX_ASSOCIATIONS,
                         MAX_STRING, SESSION_STATUSES, PR_STATES, FeatureSession,
                         remote_identity, _bounded_string, _sha, _unique_items,
                         _validate_session, validate_feature_sessions)


def create_feature_session(state: dict, *, root: Path, remote_name: str,
                           remote_url: str, base_branch: str, feature_branch: str,
                           observed_head: str | None = None) -> FeatureSession:
    """Create only by explicit request, under the caller's project-state lock."""
    _bounded_string(remote_name, "remote name", 128)
    if observed_head is not None:
        _sha(observed_head, "observed HEAD")
    repository = str(root.resolve(strict=True))
    sessions = state.get("feature_sessions", {})
    validate_feature_sessions(sessions, state["workflows"])
    if len(sessions) >= MAX_SESSIONS:
        raise Abort("Feature session collection reached its limit")
    for prior in sessions.values():
        if (prior["repository"] == repository and prior["remote_name"] == remote_name
                and prior["feature_branch"] == feature_branch and prior["status"] == "active"):
            raise Abort("An active feature session already owns this repository and branch")
    identifier = uuid.uuid4().hex
    while identifier in sessions:
        identifier = uuid.uuid4().hex
    record = {
        "session_id": identifier, "repository": repository, "remote_name": remote_name,
        "remote_identity": remote_identity(remote_url), "base_branch": base_branch,
        "feature_branch": feature_branch, "created_at": utc_now(),
        "patch_workflow_keys": [], "observed_heads": [observed_head] if observed_head else [],
        "commit_shas": [], "pr_revisions": [], "status": "active",
    }
    _validate_session(identifier, record)
    state.setdefault("feature_sessions", {})[identifier] = record
    return FeatureSession.from_record(record)


def attach_applied_workflow(state: dict, session_id: str, workflow_key: str,
                            *, history_entry) -> FeatureSession:
    """Link an applied ZIP after confirming its history and successful APL/BAP run."""
    sessions = state.get("feature_sessions", {})
    validate_feature_sessions(sessions, state["workflows"])
    record = sessions.get(session_id)
    workflow = state["workflows"].get(workflow_key)
    if record is None or record["status"] != "active":
        raise Abort("No active feature session matches the selected ID")
    if type(workflow) is not dict:
        raise Abort("Feature session link requires an existing patch workflow")
    if (workflow.get("repository") != record["repository"]
            or workflow.get("branch") != record["feature_branch"]):
        raise Abort("Feature session repository or intended feature branch differs")
    if (history_entry.patch != workflow.get("patch_file")
            or history_entry.planned_branch != workflow.get("source_branch", record["feature_branch"])
            or history_entry.real_branch not in {record["base_branch"], record["feature_branch"]}):
        raise Abort("Applied patch history does not match the feature session")
    digest = workflow.get("archive_sha256")
    if type(digest) is not str or not REMOTE_ID.fullmatch(digest):
        raise Abort("Feature session link requires a verified ZIP digest")
    if not any(
        run.get("workflow_key") == workflow_key
        and run.get("operation", {}).get("number") in (2, 3)
        and run.get("outcome") == RunOutcome.SUCCEEDED.value
        and run.get("verified_facts", {}).get("archive_sha256") == digest
        for run in state.get("operation_runs", [])
    ):
        raise Abort("Feature session link requires a successful recorded application")
    if workflow.get("session_id") not in (None, session_id):
        raise Abort("Patch workflow is already owned by another session")
    if workflow_key not in record["patch_workflow_keys"]:
        if len(record["patch_workflow_keys"]) >= MAX_ASSOCIATIONS:
            raise Abort("Feature session patch association limit reached")
        record["patch_workflow_keys"].append(workflow_key)
    workflow["session_id"] = session_id
    return FeatureSession.from_record(record)


def record_session_commit(state: dict, session_id: str, commit_sha: str) -> FeatureSession:
    """Append recorded commit evidence without asserting live Git ancestry."""
    _sha(commit_sha, "commit SHA")
    record = _active_session(state, session_id)
    if commit_sha not in record["commit_shas"]:
        if len(record["commit_shas"]) >= MAX_ASSOCIATIONS:
            raise Abort("Feature session commit limit reached")
        record["commit_shas"].append(commit_sha)
    return FeatureSession.from_record(record)


def record_session_head(state: dict, session_id: str, head_sha: str) -> FeatureSession:
    """Append a locally observed revision without making a verification claim."""
    _sha(head_sha, "observed HEAD")
    record = _active_session(state, session_id)
    if head_sha not in record["observed_heads"]:
        if len(record["observed_heads"]) >= MAX_ASSOCIATIONS:
            raise Abort("Feature session observed HEAD limit reached")
        record["observed_heads"].append(head_sha)
    return FeatureSession.from_record(record)


def record_session_pr(state: dict, session_id: str, *, number: int, head_sha: str,
                      status: str) -> FeatureSession:
    """Append a distinct observed PR revision; callers must verify remote facts."""
    _sha(head_sha, "PR HEAD")
    if type(number) is not int or number <= 0 or type(status) is not str or status not in PR_STATES:
        raise Abort("Invalid recorded PR identity")
    record = _active_session(state, session_id)
    if not any(item["number"] == number and item["head_sha"] == head_sha
               and item["state"] == status
               for item in record["pr_revisions"]):
        if len(record["pr_revisions"]) >= MAX_ASSOCIATIONS:
            raise Abort("Feature session PR revision limit reached")
        record["pr_revisions"].append({"number": number, "head_sha": head_sha, "state": status})
    return FeatureSession.from_record(record)


def close_feature_session(state: dict, session_id: str, *, status: str,
                          pr_number: int | None = None,
                          merge_sha: str | None = None) -> FeatureSession:
    """Record an explicitly authorized terminal decision, not an inferred merge."""
    record = _active_session(state, session_id)
    if status == "abandoned" and pr_number is None and merge_sha is None:
        evidence = {"kind": "DEVELOPER_ABANDONED"}
    elif status == "merged" and type(pr_number) is int and pr_number > 0:
        _sha(merge_sha, "merge commit")
        if not any(item["number"] == pr_number and item["state"] == "MERGED"
                   for item in record["pr_revisions"]):
            raise Abort("Merged session requires an independently recorded merged PR")
        evidence = {"kind": "MERGED_PR", "pr_number": pr_number, "merge_sha": merge_sha}
    else:
        raise Abort("Invalid terminal feature session decision")
    record["status"] = status
    record["terminal_evidence"] = evidence
    return FeatureSession.from_record(record)


def _active_session(state, session_id):
    validate_feature_sessions(state.get("feature_sessions", {}), state["workflows"])
    record = state.get("feature_sessions", {}).get(session_id)
    if record is None or record["status"] != "active":
        raise Abort("Feature session is missing or already terminal")
    return record
