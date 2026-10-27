"""Bounded, append-only evidence records for project-local action attempts."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import re
import uuid

from .core.actions import ACTION_CODES
from .core.enums import OperationOutcome
from .model import Abort, BASENAME_PATTERN


RUN_ID = re.compile(r"^[a-f0-9]{32}$")
MAX_RUNS = 100000


class RunOutcome(str, Enum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    NO_OP = "NO_OP"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    INDETERMINATE = "INDETERMINATE"


_JOURNAL_OUTCOMES = {
    OperationOutcome.SUCCESS: RunOutcome.SUCCEEDED,
    OperationOutcome.ALREADY_SATISFIED: RunOutcome.NO_OP,
    OperationOutcome.NO_OP: RunOutcome.NO_OP,
    OperationOutcome.ERROR: RunOutcome.FAILED,
    OperationOutcome.CANCELLED: RunOutcome.CANCELLED,
    OperationOutcome.UNKNOWN_REMOTE_RESULT: RunOutcome.INDETERMINATE,
}


def journal_outcome_for_result(result: str | OperationOutcome) -> str:
    """Centralize the public action-outcome to persisted-journal mapping."""
    try:
        return _JOURNAL_OUTCOMES[OperationOutcome(result)].value
    except (ValueError, KeyError) as exc:
        raise Abort("Unexpected action result; operation journal cannot be finalized") from exc


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _valid_timestamp(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Abort("Invalid operation run timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Abort("Invalid operation run timestamp") from exc
    if parsed.utcoffset() is None:
        raise Abort("Invalid operation run timezone")


def validate_run(run):
    """Validate persisted facts without requiring a historical workflow to exist."""
    if not isinstance(run, dict) or not isinstance(run.get("run_id"), str) or not RUN_ID.fullmatch(run["run_id"]):
        raise Abort("Invalid operation run ID")
    operation = run.get("operation")
    if (not isinstance(operation, dict) or type(operation.get("number")) is not int
            or not 1 <= operation["number"] <= 9
            or operation.get("code") != ACTION_CODES[operation["number"]]):
        raise Abort("Invalid operation run action")
    if (not isinstance(run.get("mode"), str) or run["mode"] not in {"LOOSE", "STRICT", "FORCE"}
            or not isinstance(run.get("repository"), str)
            or not Path(run["repository"]).is_absolute()
            or not isinstance(run.get("workflow_key"), str) or len(run["workflow_key"]) > 128
            or not isinstance(run.get("patch"), str)
            or not BASENAME_PATTERN.fullmatch(run["patch"])):
        raise Abort("Invalid operation run identity")
    _valid_timestamp(run.get("started_at"))
    outcome = run.get("outcome")
    if not isinstance(outcome, str) or outcome not in {item.value for item in RunOutcome}:
        raise Abort("Invalid operation run outcome")
    if outcome == RunOutcome.STARTED.value:
        if run.get("finished_at") is not None:
            raise Abort("Running operation cannot have a finished timestamp")
    else:
        _valid_timestamp(run.get("finished_at"))
    for key in ("before", "after", "verified_facts"):
        if key in run and not isinstance(run[key], dict):
            raise Abort(f"Invalid operation run {key}")
    if "sequence" in run:
        sequence = run["sequence"]
        if (not isinstance(sequence, dict) or not isinstance(sequence.get("id"), str)
                or not RUN_ID.fullmatch(sequence["id"])
                or type(sequence.get("index")) is not int or sequence["index"] < 1
                or type(sequence.get("total")) is not int
                or not sequence["index"] <= sequence["total"] <= 20):
            raise Abort("Invalid operation run sequence")
    if "error" in run:
        error = run["error"]
        if (not isinstance(error, dict) or not isinstance(error.get("category"), str)
                or not isinstance(error.get("message"), str)
                or len(error["category"]) > 80 or len(error["message"]) > 240):
            raise Abort("Invalid operation run error summary")


def validate_runs(runs):
    if not isinstance(runs, list) or len(runs) > MAX_RUNS:
        raise Abort("Invalid operation run journal size")
    seen = set()
    for run in runs:
        validate_run(run)
        if run["run_id"] in seen:
            raise Abort("Duplicate operation run ID")
        seen.add(run["run_id"])


def unresolved_runs(state, root):
    """Return STARTED attempts without changing or interpreting their outcome."""
    repository = str(Path(root).resolve())
    return [run for run in state.get("operation_runs", [])
            if run["repository"] == repository and run["outcome"] == RunOutcome.STARTED.value]


def safe_error(outcome):
    """Use fixed diagnostic text instead of arbitrary exception or CLI output."""
    messages = {
        RunOutcome.FAILED.value: ("ACTION_FAILED", "The action failed; inspect the project diagnostic log."),
        RunOutcome.CANCELLED.value: ("CONFIRMATION_DECLINED", "The action was cancelled or declined."),
        RunOutcome.INTERRUPTED.value: ("INTERRUPTED", "The process was interrupted; reconcile local state."),
        RunOutcome.INDETERMINATE.value: ("REMOTE_OUTCOME_UNKNOWN", "Inspect live remote state before retrying."),
    }
    category, message = messages[outcome]
    return {"category": category, "message": message}


@dataclass(frozen=True)
class OperationRun:
    data: dict

    @classmethod
    def start(cls, *, number, mode, root, workflow_key, patch, phase, sequence=None):
        data = {"run_id": uuid.uuid4().hex,
                "operation": {"number": number, "code": ACTION_CODES[number]},
                "mode": mode.upper(), "repository": str(Path(root).resolve()),
                "workflow_key": workflow_key, "patch": patch,
                "started_at": utc_now(), "finished_at": None,
                "outcome": RunOutcome.STARTED.value, "before": {"phase": phase}}
        if sequence is not None:
            identifier, index, total = sequence
            data["sequence"] = {"id": identifier, "index": index, "total": total}
        validate_run(data)
        return cls(data)

    @staticmethod
    def finish(data, *, outcome, before=None, after=None, verified_facts=None):
        if data["outcome"] != RunOutcome.STARTED.value:
            raise Abort("Cannot complete an already completed operation run")
        completed = dict(data, outcome=outcome, finished_at=utc_now())
        if before:
            completed["before"] = dict(data.get("before", {}), **before)
        if after:
            completed["after"] = dict(after)
        if verified_facts:
            completed["verified_facts"] = dict(verified_facts)
        if outcome in {item.value for item in (RunOutcome.FAILED, RunOutcome.CANCELLED,
                                                RunOutcome.INTERRUPTED, RunOutcome.INDETERMINATE)}:
            completed["error"] = safe_error(outcome)
        validate_run(completed)
        return completed
