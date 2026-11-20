#!/usr/bin/env python3
"""Validate the read-only SDD checkpoint without advancing or accepting work."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "docs/specs/STATE.json"
SCHEMA_PATH = ROOT / "docs/specs/state.schema.json"


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _exact_fields(value: object, fields: list[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"Invalid {label} fields")
    return value


def _matching(value: object, pattern: str, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(f"Invalid {label}")
    return value


def validate_state(source: Path = STATE_PATH, repo_root: Path = ROOT) -> dict:
    """Return a valid checkpoint or raise ValueError without changing any files."""
    if source.is_symlink() or not source.is_file():
        raise ValueError("STATE.json must be an existing regular file")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    properties = schema["properties"]
    records_contract = properties["workstreams"]
    item = records_contract["items"]
    fields = item["properties"]
    try:
        document = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid STATE.json: {error}") from error

    if not isinstance(document, dict) or not (
        set(document) in (set(schema["required"]),
                          set(schema["required"]) | {"selectedTaskPath"})
    ):
        raise ValueError("Invalid STATE.json fields")
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise ValueError("Unsupported schemaVersion")
    if document["mode"] != "SINGLE":
        raise ValueError("Only SINGLE mode is supported")
    selected = _matching(document["selectedWorkstreamId"],
                         properties["selectedWorkstreamId"]["pattern"], "selectedWorkstreamId")
    records = document["workstreams"]
    if (not isinstance(records, list) or
            not records_contract["minItems"] <= len(records) <= records_contract["maxItems"]):
        raise ValueError("Invalid workstreams length")

    identifiers: set[str] = set()
    paths: set[str] = set()
    selected_phase = None
    selected_spec_path: str | None = None
    selected_stage_id: str | None = None
    for record in records:
        record = _exact_fields(record, item["required"], "workstream")
        identifier = _matching(record["id"], fields["id"]["pattern"], "workstream ID")
        path = _matching(record["specPath"], fields["specPath"]["pattern"], "specPath")
        _matching(record["stageId"], fields["stageId"]["pattern"], "stageId")
        phase = record["phase"]
        if not isinstance(phase, str) or phase not in fields["phase"]["enum"]:
            raise ValueError("Invalid SDD phase")
        if identifier in identifiers or path in paths:
            raise ValueError("Duplicate workstream identity or specPath")
        identifiers.add(identifier)
        paths.add(path)
        spec = repo_root / path
        if spec.is_symlink() or not spec.is_file():
            raise ValueError(f"Missing or unsafe active sub-specification: {path}")
        if identifier == selected:
            selected_phase = phase
            selected_spec_path = path
            selected_stage_id = record["stageId"]
        elif phase == "READY_FOR_IMPLEMENTATION":
            raise ValueError("Only the selected SINGLE workstream may be ready for implementation")

    if selected_phase is None:
        raise ValueError("Selected workstream does not exist")
    if selected_phase in {"PAUSED", "ON_HOLD"}:
        raise ValueError("Selected workstream cannot be paused or on hold")
    if "selectedTaskPath" in document:
        task = _matching(document["selectedTaskPath"],
                         properties["selectedTaskPath"]["pattern"],
                         "selectedTaskPath")
        if selected_spec_path is None or selected_stage_id is None:
            raise ValueError("Selected task requires a selected workstream")
        task_path = Path(task)
        if task_path.parent != Path(selected_spec_path).parent:
            raise ValueError("Selected task does not belong to the selected sub-spec")
        selected_number = re.fullmatch(r"[A-Z][A-Za-z0-9.]*-([0-9]{2})", selected_stage_id)
        task_number = re.fullmatch(r"task_([0-9]{2})_[a-z0-9_]+\.md", task_path.name)
        if selected_number is None or task_number is None or selected_number.group(1) != task_number.group(1):
            raise ValueError("Selected task and stageId disagree")
        selected_task_file = repo_root / task_path
        counterpart = selected_task_file.with_name(
            "task_impl_plan_" + selected_task_file.name.removeprefix("task_"))
        for candidate in (selected_task_file, counterpart):
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError(f"Missing or unsafe selected task/plan: {candidate}")
        header = selected_task_file.read_text(encoding="utf-8").split("\n## ", 1)[0]
        types = re.findall(r"^- \*\*type:\*\* `([A-Z_]+)`\.$", header, re.MULTILINE)
        if len(types) != 1 or types[0] not in {"GEN_CODE", "GEN_TESTS", "UPD_DOCS"}:
            raise ValueError("Selected task must declare a supported type")
    return document


def main() -> int:
    try:
        state = validate_state()
    except (ValueError, OSError, KeyError) as error:
        print(f"SDD STATE INVALID: {error}", file=sys.stderr)
        return 2
    print(f"SDD STATE VALID: {state['selectedWorkstreamId']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
