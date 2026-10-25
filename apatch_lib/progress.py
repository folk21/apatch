"""Private, tool-global operation ledger independent of per-project checkpoints."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import stat
import tempfile
import time
import uuid
from pathlib import Path

from .core.actions import ACTION_CODES
from .model import Abort
from .storage.locking import exclusive_file_lock


SCHEMA_VERSION = 1
RESULTS = {"SUCCESS", "NO_OP", "CANCELLED", "FAILED", "UNKNOWN_REMOTE_RESULT"}
PROJECT_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
PROJECT_ID = re.compile(r"^[a-f0-9]{64}$")
EVENT_ID = re.compile(r"^[a-f0-9]{32}$")
MAX_MASTER_BYTES = 128 * 1024 * 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def project_identity(root: Path):
    """Represent a canonical repository root without consulting external remotes."""
    canonical = str(root.resolve(strict=True))
    normalized = os.path.normcase(os.path.normpath(canonical))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), canonical


def _safe_project_name(name: str):
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80].strip("._-")
    return sanitized or "project"


def _private_directory(path: Path):
    for directory in (path.parent, path):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise Abort(f"Unsafe global progress directory: {directory}")
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise Abort(f"Unsafe global progress directory: {directory}")
    os.chmod(path, 0o700)


def _read_json(path: Path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"Unsafe progress file: {path}")
    if not path.exists():
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            size = os.fstat(handle.fileno())
            if not stat.S_ISREG(size.st_mode) or size.st_size > MAX_MASTER_BYTES:
                raise Abort(f"Invalid progress file type or size: {path}")
            return json.load(handle)
    except (OSError, UnicodeError, ValueError) as exc:
        raise Abort(f"Cannot read global progress file {path.name}: {type(exc).__name__}") from exc


def _atomic_json(path: Path, data):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Abort(f"Unsafe global progress destination: {path.name}")
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".apatch-progress-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _empty_master():
    return {"schema_version": SCHEMA_VERSION, "projects": {}, "events": []}


def _validate_master(data):
    if (not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION
            or not isinstance(data.get("projects"), dict)
            or not isinstance(data.get("events"), list)):
        raise Abort("Malformed global progress master; inspect manually")
    filenames = set()
    for project_id, project in data["projects"].items():
        if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
            raise Abort("Malformed global progress project ID")
        if not isinstance(project, dict):
            raise Abort("Malformed global progress project entry")
        filename = project.get("history_file")
        if (not isinstance(filename, str) or not PROJECT_NAME.fullmatch(filename)
                or not filename.endswith("_progress.json") or filename in filenames):
            raise Abort("Malformed or colliding project progress filename")
        filenames.add(filename)
        root = project.get("root")
        if (not isinstance(root, str) or not Path(root).is_absolute()
                or hashlib.sha256(os.path.normcase(os.path.normpath(root)).encode()).hexdigest() != project_id
                or not isinstance(project.get("name"), str)):
            raise Abort("Invalid stored project identity")
    seen = set()
    for event in data["events"]:
        if (not isinstance(event, dict) or not isinstance(event.get("event_id"), str)
                or not EVENT_ID.fullmatch(event["event_id"]) or event["event_id"] in seen
                or not isinstance(event.get("project_id"), str)
                or event["project_id"] not in data["projects"]
                or not isinstance(event.get("result"), str)
                or event["result"] not in RESULTS):
            raise Abort("Malformed or duplicate global progress event")
        seen.add(event["event_id"])
    return data


@dataclass(frozen=True)
class ProgressEvent:
    """Bounded, already-classified record of one attempted lifecycle operation."""

    data: dict

    @classmethod
    def capture(cls, *, root, patch_file, operation_number, mode, result,
                phase_before, phase_after, branch_before, branch_after, record,
                started_at_utc, duration_seconds, error=None, sequence=None):
        project_id, canonical = project_identity(root)
        if result not in RESULTS or not 1 <= operation_number <= 10:
            raise Abort("Invalid operation summary for global progress")
        code = ACTION_CODES[operation_number]
        suggestions = {"new": 3, "branch_created": 3, "patch_applied": 4,
                       "verified": 5, "committed": 6, "pushed": 7,
                       "pr_created": 8, "merged": 9}
        next_action = suggestions.get(phase_after)
        if phase_after == "patch_applied" and record.get("zip_first") and record.get("applied_branch") == "main":
            next_action = 1
        if result in {"FAILED", "UNKNOWN_REMOTE_RESULT", "CANCELLED"}:
            next_action = None
        summary = ("Remote operation result unconfirmed; inspect live state" if result == "UNKNOWN_REMOTE_RESULT"
                   else "Confirmation declined or operation interrupted" if result == "CANCELLED"
                   else "Operation failed; inspect target project diagnostic log" if result == "FAILED"
                   else None)
        data = {
            "event_id": uuid.uuid4().hex,
            "started_at_utc": started_at_utc,
            "finished_at_utc": utc_now(),
            "project_id": project_id,
            "project_name": root.name,
            "project_root": canonical,
            "patch_file": patch_file,
            "operation_code": code,
            "operation_number": operation_number,
            "mode": mode,
            "result": result,
            "duration_seconds": round(max(0, duration_seconds), 3),
            "phase_before": phase_before,
            "phase_after": phase_after,
            "branch_before": branch_before,
            "branch_after": branch_after,
            "commit_sha": record.get("commit_sha"),
            "pr_number": record.get("pr_number"),
            "next_suggested": (f"{next_action} [{ACTION_CODES[next_action]}]" if next_action else None),
            "error_code": type(error).__name__ if error is not None else None,
            "error_summary": summary,
            "sequence_id": sequence[0] if sequence else None,
            "step_index": sequence[1] if sequence else None,
            "step_total": sequence[2] if sequence else None,
        }
        return cls(data)


class ProgressStore:
    """Append-only master with per-project rebuildable materialized JSON views."""

    def __init__(self, tool_dir: Path):
        self.directory = tool_dir / ".apatch" / "progress"
        self.master_path = self.directory / "progress.json"

    def read_snapshot(self):
        """Read the authoritative master without creating or fixing anything."""
        data = _read_json(self.master_path)
        return _validate_master(data) if data is not None else _empty_master()

    def append_event(self, event: ProgressEvent):
        _private_directory(self.directory)
        lock = self.directory / "progress.json.lock"
        with exclusive_file_lock(lock, label="global progress", wait_seconds=10):
            master = self.read_snapshot()
            payload = event.data
            project_id = payload["project_id"]
            project_root = payload["project_root"]
            project = master["projects"].get(project_id)
            if project is not None and project["root"] != project_root:
                raise Abort("Global progress project root identity mismatch")
            if project is None:
                existing = {item["history_file"] for item in master["projects"].values()}
                basename = _safe_project_name(payload["project_name"])
                name = f"{basename}_progress.json"
                if name in existing:
                    name = f"{basename}__{project_id[:12]}_progress.json"
                if name in existing:
                    raise Abort("Global progress history filename collision")
                project = {"name": payload["project_name"], "root": project_root,
                           "history_file": name, "last_event_id": None}
                master["projects"][project_id] = project
            if not any(prior["event_id"] == payload["event_id"] for prior in master["events"]):
                master["events"].append(payload)
                project["last_event_id"] = payload["event_id"]
                _atomic_json(self.master_path, master)
            for item_id, item in master["projects"].items():
                contents = {"schema_version": SCHEMA_VERSION, "project_id": item_id,
                            "project": item,
                            "events": [entry for entry in master["events"]
                                       if entry["project_id"] == item_id]}
                _atomic_json(self.directory / item["history_file"], contents)


class ProgressRecorder:
    """Buffer events while a target checkpoint lock is held; flush afterward."""

    def __init__(self, root: Path):
        self.root = root
        self.events = []

    def record(self, event: ProgressEvent):
        self.events.append(event)

    def flush(self, tool_dir: Path):
        store = ProgressStore(tool_dir)
        for event in self.events:
            try:
                store.append_event(event)
            except Exception as exc:
                print(f"WARNING: PROGRESS_UNAVAILABLE ({type(exc).__name__}); "
                      "the Git/patch outcome is unchanged. Inspect tool-local .apatch/progress/.",
                      flush=True)
