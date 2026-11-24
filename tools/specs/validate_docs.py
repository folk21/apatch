#!/usr/bin/env python3
"""Validate minimal OKF metadata and normative SDD task-to-plan routing."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMMON_FIELDS = {"type", "title", "description"}
TASK_PLAN_FIELDS = COMMON_FIELDS | {"area", "runType"}
TYPE_AREAS = {"GEN_CODE": "CODE", "UPD_DOCS": "DOCS", "GEN_TESTS": "E2E_TESTS"}
FEATURE_ID = re.compile(r"[A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9_]*)+")
TASK_ID = re.compile(r"RE-[0-9]{2}")
TASK_PLAN_NAME = re.compile(r"task_impl_plan_([0-9]{2})_[a-z0-9_]+\.md")
RUNTIME_DIRECTORIES = frozenset({
    ".apatch", ".git", ".venv", ".tox", ".pytest_cache", ".mypy_cache",
    "__pycache__", "build", "dist", "logs", "node_modules",
})


def repository_markdown(root: Path) -> list[Path]:
    """Find source Markdown while excluding ignored runtime and backup directories."""
    files: list[Path] = []
    for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directories[:] = sorted(name for name in directories
                                if name not in RUNTIME_DIRECTORIES)
        for name in filenames:
            if name.endswith(".md"):
                files.append(Path(directory) / name)
    return sorted(files)


class _UniqueSafeLoader(yaml.SafeLoader):
    """Refuse duplicate front matter keys before semantic validation."""


def _mapping(loader: _UniqueSafeLoader, node: yaml.MappingNode) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if type(key) is not str or key in result:
            raise ValueError("Duplicate or non-string metadata key")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse_header(file: Path) -> tuple[dict, str]:
    """Return validated minimal YAML front matter and unchanged Markdown body."""
    if file.is_symlink() or not file.is_file():
        raise ValueError(f"Missing or unsafe Markdown document: {file}")
    raw = file.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"Missing OKF front matter: {file}")
    marker = raw.find("\n---\n", 4)
    if marker < 0 or marker > 16384:
        raise ValueError(f"Unterminated or oversized OKF front matter: {file}")
    try:
        info = yaml.load(raw[4:marker], Loader=_UniqueSafeLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid OKF YAML: {file}: {exc}") from exc
    if not isinstance(info, dict) or not COMMON_FIELDS <= set(info):
        raise ValueError(f"Missing OKF type/title/description: {file}")
    if any(type(info[key]) is not str or not info[key].strip() or len(info[key]) > 512
           for key in COMMON_FIELDS):
        raise ValueError(f"Invalid OKF type/title/description: {file}")
    is_task_plan = TASK_PLAN_NAME.fullmatch(file.name) is not None
    expected = TASK_PLAN_FIELDS if is_task_plan else COMMON_FIELDS
    if set(info) != expected:
        raise ValueError(f"Unexpected or missing OKF fields: {file}; expected {sorted(expected)}")
    if is_task_plan and any(type(info[key]) is not str or not info[key].strip()
                            for key in ("area", "runType")):
        raise ValueError(f"Invalid task-plan routing fields: {file}")
    body = raw[marker + len("\n---\n"):]
    heading = re.search(r"(?m)^# (.+)$", body)
    if not heading or info["title"] != heading.group(1).strip():
        raise ValueError(f"OKF title differs from primary heading: {file}")
    return info, body


def _features(root: Path) -> set[str]:
    catalog = (root / "docs/FEATURES.md").read_text(encoding="utf-8")
    return set(re.findall(r"(?m)^\| `([A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9_]*)+)` \|", catalog))


def _normative_task_sections(text: str) -> dict[str, str]:
    """Extract exact task sections; metadata is authoritative only here."""
    matches = list(re.finditer(r"(?m)^### (RE-[0-9]{2})\s*$", text))
    if not matches:
        raise ValueError("Normative sub-spec has no task sections")
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        task_id = match.group(1)
        if task_id in sections:
            raise ValueError(f"Duplicate normative task: {task_id}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[task_id] = text[match.end():end].split("\n## ", 1)[0]
    return sections


def _one(section: str, key: str, task_id: str) -> str:
    matches = re.findall(r"(?m)^- \*\*" + re.escape(key) + r":\*\* (.+)\.$", section)
    if len(matches) != 1:
        raise ValueError(f"Missing or duplicated normative {key} for {task_id}")
    return matches[0]


def _normative_table(text: str) -> dict[str, tuple[str, str, str, str]]:
    """Validate classification in the human-readable task index as well."""
    rows: dict[str, tuple[str, str, str, str]] = {}
    for line in text.splitlines():
        if not line.startswith("| [`RE-"):
            continue
        columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(columns) != 7:
            raise ValueError("Normative task table must declare run type")
        match = re.fullmatch(r"\[`(RE-[0-9]{2})`\]\(#re-[0-9]{2}\)", columns[0])
        if not match or match.group(1) in rows:
            raise ValueError("Invalid or duplicate normative task table entry")
        quoted = [re.fullmatch(r"`([A-Z0-9_]+)`", col) for col in columns[1:4]]
        plan = re.fullmatch(r"\[Plan\]\((task_impl_plan_[0-9]{2}_[a-z0-9_]+\.md)\)",
                            columns[5])
        if not all(quoted) or plan is None:
            raise ValueError(f"Invalid normative task table classification: {match.group(1)}")
        rows[match.group(1)] = (quoted[0].group(1), quoted[1].group(1),
                                quoted[2].group(1), plan.group(1))
    return rows


def validate_documents(root: Path = ROOT) -> dict[str, dict]:
    """Validate repository Markdown and exact plan/section classification consistency."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid repository root")
    documents = repository_markdown(root)
    if not documents:
        raise ValueError("No Markdown documents found")
    metadata: dict[str, dict] = {}
    for file in documents:
        name = file.relative_to(root).as_posix()
        info, _ = parse_header(file)
        if name.startswith("docs/specs/") and name not in {"docs/specs/AGENTS.md", "docs/specs/README.md"}:
            if TASK_PLAN_NAME.fullmatch(file.name):
                if file.parent not in {
                    root / "docs/specs/active/review-evidence",
                    root / "docs/specs/archive/workstreams/review-evidence",
                }:
                    raise ValueError(f"Unexpected task-plan location: {name}")
            elif file.name.endswith("-implementation-plan.md"):
                if info["type"] != "Implementation Guide":
                    raise ValueError(f"Invalid standalone implementation-plan type: {name}")
            elif info["type"] != "Specification":
                raise ValueError(f"Invalid SDD specification type: {name}")
        metadata[name] = info

    locations = (
        root / "docs/specs/active/review-evidence/subspec.md",
        root / "docs/specs/archive/workstreams/review-evidence/subspec.md",
    )
    available = [path for path in locations if path.exists() or path.is_symlink()]
    if len(available) != 1 or available[0].is_symlink() or not available[0].is_file():
        raise ValueError("Expected one safe normative review-evidence sub-spec")
    sub = available[0]
    normative = sub.read_text(encoding="utf-8")
    sections = _normative_task_sections(normative)
    table = _normative_table(normative)
    expected = {f"RE-{number:02d}" for number in range(1, 8)}
    if set(sections) != expected or set(table) != expected:
        raise ValueError("Review-evidence task or normative table coverage is incomplete")
    known = _features(root)
    plan_dir = sub.parent.relative_to(root).as_posix() + "/"
    seen_plans: set[str] = set()
    for task_id, section in sections.items():
        task_type = _one(section, "type", task_id).strip("`")
        area = _one(section, "area", task_id).strip("`")
        rtype = _one(section, "rtype", task_id).strip("`")
        feature_row = _one(section, "feature_ids", task_id)
        features = re.findall(r"`([A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9_]*)+)`", feature_row)
        if (not features or len(features) != len(set(features)) or
                set(features) - known or any(not FEATURE_ID.fullmatch(x) for x in features)):
            raise ValueError(f"Invalid normative feature_ids for {task_id}")
        if task_type not in TYPE_AREAS or area != TYPE_AREAS[task_type]:
            raise ValueError(f"Invalid normative task type/area: {task_id}")
        expected_run_type = "ACCEPT" if task_type == "GEN_TESTS" else "DEVELOP"
        if rtype != expected_run_type:
            raise ValueError(f"Invalid normative rtype: {task_id}")
        plan_row = _one(section, "Implementation plan", task_id)
        plan_match = re.fullmatch(r"\[[^\]\n]+\]\((task_impl_plan_[0-9]{2}_[a-z0-9_]+\.md)\)", plan_row)
        if plan_match is None:
            raise ValueError(f"Invalid normative task plan link: {task_id}")
        plan_name = plan_match.group(1)
        plan_number = TASK_PLAN_NAME.fullmatch(plan_name)
        if not plan_number or task_id != "RE-" + plan_number.group(1):
            raise ValueError(f"Task plan filename disagrees with normative ID: {task_id}")
        if table[task_id] != (task_type, area, rtype, plan_name):
            raise ValueError(f"Task table disagrees with normative task section: {task_id}")
        path = plan_dir + plan_name
        if path in seen_plans or path not in metadata:
            raise ValueError(f"Missing or duplicate advisory task plan for {task_id}")
        seen_plans.add(path)
        info = metadata[path]
        if (info["type"], info["area"], info["runType"]) != (task_type, area, rtype):
            raise ValueError(f"Task-plan OKF routing disagrees with normative sub-spec: {path}")
    actual_plans = {name for name in metadata if name.startswith(plan_dir)
                    and TASK_PLAN_NAME.fullmatch(Path(name).name)}
    if actual_plans != seen_plans:
        raise ValueError("Unlinked or extra review-evidence task plan")
    return metadata


def main() -> int:
    try:
        metadata = validate_documents()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"OKF DOCUMENTS INVALID: {exc}", file=sys.stderr)
        return 2
    print(f"OKF DOCUMENTS VALID: {len(metadata)} Markdown documents, 7 typed task plans")
    return 0


if __name__ == "__main__":
    sys.exit(main())
