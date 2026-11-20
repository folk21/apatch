#!/usr/bin/env python3
"""Validate the documentation-only feature catalog and owner cross-reference."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path, PurePosixPath

import yaml


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "docs/FEATURES.md"
CROSS_REF = ROOT / "docs/specs/feature-cross-ref.yaml"
SCHEMA = ROOT / "docs/specs/feature-cross-ref.schema.json"


class UniqueLoader(yaml.SafeLoader):
    """Reject ambiguous YAML mappings rather than keeping the final value."""


def _unique_mapping(loader: UniqueLoader, node: yaml.MappingNode) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise ValueError("Invalid or duplicate YAML mapping key")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _safe_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError(f"Invalid feature path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in (".", "..") for part in path.parts):
        raise ValueError(f"Invalid feature path: {name}")
    target = root.joinpath(*path.parts)
    if not target.is_file() or any(part.is_symlink() for part in [target, *list(target.parents)[:len(path.parts)-1]]):
        raise ValueError(f"Missing or unsafe feature path: {name}")
    return target


def validate_features(source: Path = CROSS_REF, root: Path = ROOT) -> list[dict]:
    """Validate schema shape, feature IDs, current paths and declared Python symbols."""
    schema = json.loads((root / "docs/specs/feature-cross-ref.schema.json").read_text())
    try:
        data = yaml.load(source.read_text(encoding="utf-8"), Loader=UniqueLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid feature YAML: {error}") from error
    if not isinstance(data, dict) or set(data) != set(schema["required"]):
        raise ValueError("Invalid feature cross-reference fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != schema["properties"]["schema_version"]["const"]:
        raise ValueError("Unsupported feature schema version")
    records = data["features"]
    if not isinstance(records, list) or not records:
        raise ValueError("Missing feature records")
    catalog = (root / "docs/FEATURES.md").read_text(encoding="utf-8")
    catalog_ids = re.findall(r"(?m)^\| `([A-Z0-9_.]+)` \|", catalog)
    if len(set(catalog_ids)) != len(catalog_ids) or not catalog_ids:
        raise ValueError("Duplicate or empty feature catalog")
    entry_schema = schema["properties"]["features"]["items"]
    patterns = entry_schema["properties"]
    ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != set(entry_schema["required"]):
            raise ValueError("Invalid feature record fields")
        fid = record["feature_id"]
        if not isinstance(fid, str) or not re.fullmatch(patterns["feature_id"]["pattern"], fid):
            raise ValueError(f"Invalid feature ID: {fid}")
        if fid in ids or fid not in catalog_ids:
            raise ValueError(f"Duplicate or unknown feature ID: {fid}")
        ids.add(fid)
        status = record["implementation_status"]
        if status not in patterns["implementation_status"]["enum"]:
            raise ValueError(f"Invalid feature status: {fid}")
        for field in ("stages", "spec_paths", "owners", "test_files"):
            values = record[field]
            rule = patterns[field]
            if (not isinstance(values, list) or
                    len({str(value) for value in values}) != len(values) or
                    any(not isinstance(value, str) or not re.fullmatch(rule["items"]["pattern"], value)
                        for value in values) or
                    len(values) < rule.get("minItems", 0)):
                raise ValueError(f"Invalid {field}: {fid}")
        if status == "planned" and (record["owners"] or record["test_files"]):
            raise ValueError(f"Planned feature has implementation claims: {fid}")
        if status in {"partial", "verified"} and not (record["owners"] and record["test_files"]):
            raise ValueError(f"Feature needs source and test owners: {fid}")
        for spec in record["spec_paths"]:
            content = _safe_file(root, spec).read_text(encoding="utf-8")
            if not all(stage in content for stage in record["stages"]):
                raise ValueError(f"Stage is absent from referenced specification: {fid}")
        for test in record["test_files"]:
            _safe_file(root, test)
        for owner in record["owners"]:
            name, sep, symbol = owner.partition("#")
            code = _safe_file(root, name)
            if sep:
                if code.suffix != ".py":
                    raise ValueError(f"Python symbol requested in non-Python owner: {fid}")
                declarations = ast.parse(code.read_text(encoding="utf-8"))
                symbols = {node.name for node in declarations.body if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                if symbol not in symbols:
                    raise ValueError(f"Missing Python owner symbol: {fid} {symbol}")
    if ids != set(catalog_ids):
        raise ValueError("Feature catalog and cross-reference IDs differ")
    return records


def main() -> int:
    try:
        entries = validate_features()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"FEATURE CROSS-REF INVALID: {error}", file=sys.stderr)
        return 2
    print(f"FEATURE CROSS-REF VALID: {len(entries)} features")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
