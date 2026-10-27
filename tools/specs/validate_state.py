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

    document = _exact_fields(document, schema["required"], "STATE.json")
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
        elif phase == "READY_FOR_IMPLEMENTATION":
            raise ValueError("Only the selected SINGLE workstream may be ready for implementation")

    if selected_phase is None:
        raise ValueError("Selected workstream does not exist")
    if selected_phase in {"PAUSED", "ON_HOLD"}:
        raise ValueError("Selected workstream cannot be paused or on hold")
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
