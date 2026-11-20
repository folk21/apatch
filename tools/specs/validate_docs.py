#!/usr/bin/env python3
"""Validate repository Markdown metadata and typed SDD task-plan headers."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMMON_FIELDS = {"type", "title", "description"}
SPEC_STATUSES = {"draft", "planned", "active", "verification-pending", "completed", "archived"}
SDD_ROLES = {"umbrella", "subspec", "implementation_plan", "task_plan"}
TYPE_AREAS = {"GEN_CODE": "CODE", "UPD_DOCS": "DOCS", "GEN_TESTS": "E2E_TESTS"}
TASK_FIELDS = {"task_id", "task_type", "area", "rtype", "feature_ids", "plan_status"}
FEATURE_ID = re.compile(r"[A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9_]*)+")
TASK_ID = re.compile(r"RE-[0-9]{2}")
RUNTIME_DIRECTORIES = frozenset({
    ".apatch", ".git", ".venv", ".tox", ".pytest_cache", ".mypy_cache",
    "__pycache__", "build", "dist", "logs", "node_modules",
})


def repository_markdown(root: Path) -> list[Path]:
    """Find source Markdown while pruning generated/runtime directories."""
    files: list[Path] = []
    for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directories[:] = sorted(name for name in directories
                                if name not in RUNTIME_DIRECTORIES)
        for name in filenames:
            if name.endswith(".md"):
                files.append(Path(directory) / name)
    return sorted(files)


class _UniqueSafeLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate metadata keys before applying semantic rules."""


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
    """Read a bounded YAML front matter block and return its unchanged Markdown body."""
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
    body = raw[marker + len("\n---\n"):]
    heading = re.search(r"(?m)^# (.+)$", body)
    if not heading or info["title"] != heading.group(1).strip():
        raise ValueError(f"OKF title differs from primary heading: {file}")
    return info, body


def _safe_parent(root: Path, path: Path, target: str) -> Path:
    """Resolve a local Markdown parent without leaving the repository."""
    if (not isinstance(target, str) or not target or target.startswith("/")
            or "\\" in target or not target.endswith(".md")
            or any(part in {"", "."} for part in target.split("/"))):
        raise ValueError(f"Invalid SDD parent path: {path}")
    source = path.parent / target
    absolute = source.resolve()
    if not absolute.is_relative_to(root.resolve()):
        raise ValueError(f"SDD parent leaves repository: {path}")
    if (source.is_symlink() or not source.is_file()
            or any(part.is_symlink() for part in [source.parent, source.parent.parent])):
        raise ValueError(f"Missing or unsafe SDD parent: {path}")
    return absolute


def _features(root: Path) -> set[str]:
    catalog = (root / "docs/FEATURES.md").read_text(encoding="utf-8")
    return set(re.findall(r"(?m)^\| `([A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9_]*)+)` \|", catalog))


def validate_documents(root: Path = ROOT) -> dict[str, dict]:
    """Validate source Markdown, SDD parents, and task plans against normative tasks."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid repository root")
    documents = repository_markdown(root)
    if not documents:
        raise ValueError("No Markdown documents found")
    metadata: dict[str, dict] = {}
    text_by_path: dict[str, str] = {}
    for file in documents:
        name = file.relative_to(root).as_posix()
        info, body = parse_header(file)
        if name.startswith("docs/specs/") and name not in {"docs/specs/AGENTS.md", "docs/specs/README.md"}:
            if (info.get("type") not in {"Specification", "Implementation Guide"}
                    or info.get("document_role") not in SDD_ROLES
                    or info.get("spec_status") not in SPEC_STATUSES):
                raise ValueError(f"Invalid SDD role/type/status: {name}")
            role = info["document_role"]
            if role == "umbrella":
                if name != "docs/specs/umbrella_spec_apatch.md" or "parent" in info:
                    raise ValueError(f"Invalid umbrella header: {name}")
            else:
                parent = _safe_parent(root, file, info.get("parent"))
                if role == "task_plan":
                    if info["type"] != "Implementation Guide" or not TASK_FIELDS <= set(info):
                        raise ValueError(f"Missing task-plan OKF fields: {name}")
                    if parent.name != "subspec.md":
                        raise ValueError(f"Invalid task-plan normative parent: {name}")
                elif role == "implementation_plan":
                    if info["type"] != "Implementation Guide" or not parent.name.startswith("subspec-"):
                        raise ValueError(f"Invalid implementation-plan header: {name}")
                elif info["type"] != "Specification" or parent.name != "umbrella_spec_apatch.md":
                    raise ValueError(f"Invalid sub-specification parent: {name}")
            if role != "task_plan" and TASK_FIELDS & set(info):
                raise ValueError(f"Task-only metadata on non-task document: {name}")
        metadata[name], text_by_path[name] = info, body

    known_features = _features(root)
    seen_ids: set[str] = set()
    for name, info in metadata.items():
        if info.get("document_role") != "task_plan":
            continue
        task_id = info["task_id"]
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id) or task_id in seen_ids:
            raise ValueError(f"Invalid or duplicate task_id: {name}")
        seen_ids.add(task_id)
        task_type = info["task_type"]
        if task_type not in TYPE_AREAS or info["area"] != TYPE_AREAS[task_type]:
            raise ValueError(f"Invalid task_type/area: {name}")
        expected_rtype = "ACCEPT" if task_type == "GEN_TESTS" else "DEVELOP"
        if info["rtype"] != expected_rtype or info["plan_status"] != "advisory":
            raise ValueError(f"Invalid rtype or advisory plan status: {name}")
        ids = info["feature_ids"]
        if (not isinstance(ids, list) or not ids or any(type(v) is not str or not FEATURE_ID.fullmatch(v)
                for v in ids) or len(ids) != len(set(ids)) or set(ids) - known_features):
            raise ValueError(f"Invalid task feature_ids: {name}")
        if not Path(name).name.startswith("task_impl_plan_" + task_id.split("-")[1] + "_"):
            raise ValueError(f"Task ID disagrees with task plan filename: {name}")
        normative = text_by_path[(Path(name).parent / info["parent"]).as_posix()]
        section = re.search(r"(?ms)^### " + re.escape(task_id) + r"\n(.*?)(?=^### RE-[0-9]{2}\n|\Z)", normative)
        if section is None:
            raise ValueError(f"Task not found in normative sub-spec: {name}")
        content = section.group(1)
        match_type = re.search(r"(?m)^- \*\*type:\*\* `([A-Z0-9_]+)`\.$", content)
        match_area = re.search(r"(?m)^- \*\*area:\*\* `([A-Z0-9_]+)`\.$", content)
        match_features = re.search(r"(?m)^- \*\*feature_ids:\*\* (.+)\.$", content)
        if not (match_type and match_area and match_features):
            raise ValueError(f"Missing normative task metadata for {name}")
        normative_ids = re.findall(r"`([A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9_]*)+)`", match_features.group(1))
        if (match_type.group(1) != task_type or match_area.group(1) != info["area"]
                or normative_ids != ids):
            raise ValueError(f"Task-plan OKF metadata disagrees with normative sub-spec: {name}")
    expected = {"RE-01", "RE-02", "RE-03", "RE-04", "RE-05", "RE-06", "RE-07"}
    if seen_ids != expected:
        raise ValueError("Active task-plan header coverage is incomplete")
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
