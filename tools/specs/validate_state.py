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
                          set(schema["required"]) | {"selectedTaskId"})
    ):
        raise ValueError("Invalid STATE.json fields")
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise ValueError("Unsupported schemaVersion")
    if document["mode"] == "IDLE":
        if (document["selectedWorkstreamId"] is not None or
                document["workstreams"] != [] or "selectedTaskId" in document):
            raise ValueError("IDLE requires null selection, empty workstreams and no task")
        return document
    if document["mode"] != "SINGLE":
        raise ValueError("Only SINGLE or IDLE mode is supported")
    selected = _matching(document["selectedWorkstreamId"],
                         properties["selectedWorkstreamId"]["pattern"], "selectedWorkstreamId")
    records = document["workstreams"]
    if (not isinstance(records, list) or
            not 1 <= len(records) <= records_contract["maxItems"]):
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
    if selected_spec_path is None or selected_stage_id is None:
        raise ValueError("Selected task requires a selected workstream")
    spec_text = (repo_root / selected_spec_path).read_text(encoding="utf-8")
    heading = re.compile(r"(?m)^### ([A-Z][A-Za-z0-9.]*-[0-9]{2})$", re.MULTILINE)
    matches = list(heading.finditer(spec_text))
    if not matches:
        raise ValueError("Selected sub-spec has no normative task sections")
    known_features = set(re.findall(
        r"(?m)^\| `([A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9_]*)+)` \|",
        (repo_root / "docs/FEATURES.md").read_text(encoding="utf-8")))
    seen_ids: set[str] = set()
    seen_plans: set[str] = set()
    task_types: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        task_id = match.group(1)
        if task_id in seen_ids:
            raise ValueError(f"Duplicate task ID: {task_id}")
        seen_ids.add(task_id)
        task_end = matches[index + 1].start() if index + 1 < len(matches) else len(spec_text)
        section = spec_text[match.end():task_end].split("\n## ", 1)[0]
        task_type = re.findall(r"(?m)^- \*\*type:\*\* `([A-Z0-9_]+)`\.$", section)
        area = re.findall(r"(?m)^- \*\*area:\*\* `([A-Z0-9_]+)`\.$", section)
        plan = re.findall(
            r"(?m)^- \*\*Implementation plan:\*\* \[[^]\n]+\]\((task_impl_plan_[0-9]{2}_[a-z0-9_]+\.md)\)\.$",
            section)
        feature_row = re.findall(r"(?m)^- \*\*feature_ids:\*\* (.+)\.$", section)
        if len(task_type) != 1 or task_type[0] not in {"GEN_CODE", "GEN_TESTS", "UPD_DOCS"}:
            raise ValueError(f"Invalid task type for {task_id}")
        if len(area) != 1 or area[0] not in {"CODE", "DOCS", "E2E_TESTS"}:
            raise ValueError(f"Invalid task area for {task_id}")
        allowed_area = {"GEN_CODE": {"CODE"},
                        "GEN_TESTS": {"E2E_TESTS"}, "UPD_DOCS": {"DOCS"}}
        if area[0] not in allowed_area[task_type[0]]:
            raise ValueError(f"Task type/area conflict for {task_id}")
        if len(plan) != 1 or plan[0] in seen_plans or not plan[0].startswith(
                f"task_impl_plan_{task_id.rsplit('-', 1)[1]}_"):
            raise ValueError(f"Invalid task plan for {task_id}")
        seen_plans.add(plan[0])
        planned = repo_root / Path(selected_spec_path).parent / plan[0]
        if planned.is_symlink() or not planned.is_file():
            raise ValueError(f"Missing or unsafe task plan: {planned}")
        if len(feature_row) != 1:
            raise ValueError(f"Missing feature IDs for {task_id}")
        actual_features = re.findall(r"`([A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9_]*)+)`", feature_row[0])
        if not actual_features or len(actual_features) != len(set(actual_features)) or (
                set(actual_features) - known_features):
            raise ValueError(f"Invalid feature IDs for {task_id}")
        task_types.append((task_type[0], area[0]))
    if task_types[-2:] != [("UPD_DOCS", "DOCS"), ("GEN_TESTS", "E2E_TESTS")]:
        raise ValueError("Last tasks must be UPD_DOCS/DOCS and GEN_TESTS/E2E_TESTS")
    if "selectedTaskId" in document:
        chosen = _matching(document["selectedTaskId"],
                           properties["selectedTaskId"]["pattern"], "selectedTaskId")
        if chosen not in seen_ids:
            raise ValueError("Missing selected task in selected sub-spec")
        if chosen != selected_stage_id:
            raise ValueError("Selected task and stageId disagree")
    elif selected_stage_id not in seen_ids:
        raise ValueError("Selected stageId is absent from the sub-spec")
    return document


def main() -> int:
    try:
        state = validate_state()
    except (ValueError, OSError, KeyError) as error:
        print(f"SDD STATE INVALID: {error}", file=sys.stderr)
        return 2
    print(f"SDD STATE VALID: {state['mode']}" if state["mode"] == "IDLE"
          else f"SDD STATE VALID: {state['selectedWorkstreamId']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())