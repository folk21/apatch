"""Additive feature-session records; never authorize Git or GitHub operations."""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .model import Abort, validate_base_branch
from .operation_events import RunOutcome, utc_now


SESSION_ID = re.compile(r"^[a-f0-9]{32}$")
SHA = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
REMOTE_ID = re.compile(r"^[a-f0-9]{64}$")
MAX_SESSIONS = 10000
MAX_ASSOCIATIONS = 10000
MAX_STRING = 4096
SESSION_STATUSES = frozenset({"active", "merged", "abandoned"})
PR_STATES = frozenset({"OPEN", "CLOSED", "MERGED"})
_REQUIRED = frozenset({
    "session_id", "repository", "remote_name", "remote_identity", "base_branch",
    "feature_branch", "created_at", "patch_workflow_keys", "observed_heads",
    "commit_shas", "pr_revisions", "status",
})


@dataclass(frozen=True)
class FeatureSession:
    """Immutable view of one explicitly selected development session."""

    session_id: str
    repository: str
    remote_name: str
    remote_identity: str
    base_branch: str
    feature_branch: str
    created_at: str
    patch_workflow_keys: tuple[str, ...]
    observed_heads: tuple[str, ...]
    commit_shas: tuple[str, ...]
    pr_revisions: tuple[tuple[int, str, str], ...]
    status: str

    @classmethod
    def from_record(cls, record: dict) -> "FeatureSession":
        return cls(
            session_id=record["session_id"], repository=record["repository"],
            remote_name=record["remote_name"], remote_identity=record["remote_identity"],
            base_branch=record["base_branch"], feature_branch=record["feature_branch"],
            created_at=record["created_at"],
            patch_workflow_keys=tuple(record["patch_workflow_keys"]),
            observed_heads=tuple(record["observed_heads"]),
            commit_shas=tuple(record["commit_shas"]),
            pr_revisions=tuple((item["number"], item["head_sha"], item["state"])
                               for item in record["pr_revisions"]),
            status=record["status"],
        )


def remote_identity(value: str) -> str:
    """Store a fingerprint, never a remote URL that could contain credentials."""
    _bounded_string(value, "remote URL", MAX_STRING)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_string(value, field, limit=MAX_STRING):
    if (type(value) is not str or not value or len(value) > limit
            or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise Abort(f"Invalid feature session {field}")


def _sha(value, field):
    if type(value) is not str or not SHA.fullmatch(value):
        raise Abort(f"Invalid feature session {field}: expected a full Git revision")


def _unique_items(value, label, validator):
    if type(value) is not list or len(value) > MAX_ASSOCIATIONS:
        raise Abort(f"Invalid feature session {label}: expected a bounded list")
    seen = set()
    for item in value:
        validator(item)
        if item in seen:
            raise Abort(f"Duplicate feature session {label} entry")
        seen.add(item)


def _validate_session(key, record):
    if type(key) is not str or not SESSION_ID.fullmatch(key):
        raise Abort("Invalid feature session ID")
    if type(record) is not dict or not _REQUIRED.issubset(record):
        raise Abort("Invalid feature session record: missing required fields")
    if record["session_id"] != key:
        raise Abort("Feature session key and stored ID differ")
    for field in ("repository", "remote_name", "base_branch", "feature_branch", "created_at"):
        _bounded_string(record[field], field)
    if not Path(record["repository"]).is_absolute() or ".." in Path(record["repository"]).parts:
        raise Abort("Invalid feature session repository root")
    if type(record["remote_identity"]) is not str or not REMOTE_ID.fullmatch(record["remote_identity"]):
        raise Abort("Invalid feature session remote identity")
    for field in ("base_branch", "feature_branch"):
        validate_base_branch(record[field], source="feature session")
    if record["base_branch"] == record["feature_branch"]:
        raise Abort("Feature session base and feature branches must differ")
    try:
        timestamp = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
        if timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
            raise ValueError("not UTC")
    except ValueError as exc:
        raise Abort("Invalid feature session timestamp") from exc
    if type(record["status"]) is not str or record["status"] not in SESSION_STATUSES:
        raise Abort("Invalid feature session status")
    _unique_items(record["patch_workflow_keys"], "patch workflow",
                  lambda item: _bounded_string(item, "workflow key", 512))
    _unique_items(record["observed_heads"], "observed HEAD",
                  lambda item: _sha(item, "observed HEAD"))
    _unique_items(record["commit_shas"], "commit SHA",
                  lambda item: _sha(item, "commit SHA"))
    revisions = record["pr_revisions"]
    if type(revisions) is not list or len(revisions) > MAX_ASSOCIATIONS:
        raise Abort("Invalid feature session PR revisions")
    seen_prs = set()
    for revision in revisions:
        if (type(revision) is not dict or type(revision.get("number")) is not int
                or revision["number"] <= 0 or type(revision.get("state")) is not str
                or revision["state"] not in PR_STATES):
            raise Abort("Invalid feature session PR revision")
        _sha(revision.get("head_sha"), "PR HEAD")
        pair = (revision["number"], revision["head_sha"], revision["state"])
        if pair in seen_prs:
            raise Abort("Duplicate feature session PR revision")
        seen_prs.add(pair)
    terminal = record.get("terminal_evidence")
    if record["status"] == "active":
        if terminal is not None:
            raise Abort("Active feature session cannot have terminal evidence")
    elif record["status"] == "abandoned":
        if terminal != {"kind": "DEVELOPER_ABANDONED"}:
            raise Abort("Abandoned feature session requires explicit developer evidence")
    elif (type(terminal) is not dict or terminal.get("kind") != "MERGED_PR"
          or type(terminal.get("pr_number")) is not int or terminal["pr_number"] <= 0):
        raise Abort("Merged feature session requires a recorded PR identity")
    else:
        _sha(terminal.get("merge_sha"), "merge commit")


def validate_feature_sessions(sessions, workflows):
    """Validate internal references without consulting or modifying live Git."""
    if type(sessions) is not dict or len(sessions) > MAX_SESSIONS:
        raise Abort("Invalid feature session collection")
    owners = {}
    for session_id, record in sessions.items():
        _validate_session(session_id, record)
        for key in record["patch_workflow_keys"]:
            workflow = workflows.get(key)
            if (type(workflow) is not dict or workflow.get("repository") != record["repository"]
                    or workflow.get("branch") != record["feature_branch"]):
                raise Abort("Feature session references an absent or unrelated patch workflow")
            if workflow.get("session_id") not in (None, session_id):
                raise Abort("Feature session and workflow owners conflict")
            if key in owners:
                raise Abort("Patch workflow belongs to more than one feature session")
            owners[key] = session_id
    for key, workflow in workflows.items():
        if "session_id" in workflow:
            linked = workflow["session_id"]
            if type(linked) is not str or owners.get(key) != linked:
                raise Abort("Patch workflow has a missing or inconsistent feature session")


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
            or history_entry.planned_branch != record["feature_branch"]
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
