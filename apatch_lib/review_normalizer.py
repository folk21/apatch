"""Normalize explicitly configured scanner reports without trusting wrapper verdicts."""

import hashlib
import json
import os
from pathlib import Path

from .model import Abort, safe_relative


MAX_REPORT_NODES = 50000
MAX_REPORT_DEPTH = 24
MAX_FINDINGS = 512
SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
STATUSES = {"SUCCEEDED", "FINDINGS", "FAILED", "TIMED_OUT", "UNKNOWN"}


def _fail(message):
    raise Abort(f"REVIEW_REPORT_INVALID: {message}")


def _unique_object(pairs):
    """Reject duplicate keys that could conceal scanner outcomes."""
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate JSON member")
        result[key] = value
    return result


def _reject_constant(value):
    _fail("nonfinite JSON numeric value")


def _bounded_tree(node):
    """Reject deeply nested or oversized JSON even when encoded bytes are bounded."""
    stack = [(node, 0)]
    visited = 0
    while stack:
        value, depth = stack.pop()
        visited += 1
        if visited > MAX_REPORT_NODES or depth > MAX_REPORT_DEPTH:
            _fail("report complexity exceeds limits")
        if isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)


def _short(value, label, limit=1200, *, allow_empty=False):
    if (type(value) is not str or len(value) > limit
            or (not allow_empty and not value.strip())
            or any(ord(c) < 32 and c not in "\n\t" for c in value)):
        _fail(f"invalid {label}")
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        _fail(f"invalid UTF-8 in {label}")
    return value


def _line(value):
    if type(value) is not int or not 1 <= value <= 100000000:
        _fail("invalid source line")
    return value


def _path(root, value):
    value = _short(value, "source path", 512)
    if (":" in value or "%" in value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        _fail("unsafe source path")
    try:
        safe_relative(value)
    except Abort:
        _fail("unsafe source path")
    location = root
    for component in value.split("/"):
        location = location / component
        if location.is_symlink():
            _fail("symlinked source path")
    return value


def _required_list(value, label):
    if type(value) is not list or len(value) > MAX_FINDINGS:
        _fail(f"{label} must be a bounded list")
    return value


def _ruff(data):
    for item in _required_list(data, "Ruff report"):
        if type(item) is not dict or type(item.get("location")) is not dict:
            _fail("malformed Ruff finding")
        code = _short(item.get("code"), "Ruff code", 128)
        yield code, "medium", item.get("filename"), item["location"].get("row"), item.get("message")


def _bandit(data):
    if type(data) is not dict or type(data.get("errors", [])) is not list or data.get("errors"):
        _fail("Bandit scanner errors or invalid report")
    for item in _required_list(data.get("results"), "Bandit results"):
        if type(item) is not dict:
            _fail("malformed Bandit finding")
        level = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}.get(item.get("issue_severity"))
        if level is None:
            _fail("unsupported Bandit severity")
        yield item.get("test_id"), level, item.get("filename"), item.get("line_number"), item.get("issue_text")


def _semgrep(data):
    if type(data) is not dict or type(data.get("errors", [])) is not list or data.get("errors"):
        _fail("Semgrep scanner errors or invalid report")
    for item in _required_list(data.get("results"), "Semgrep results"):
        if (type(item) is not dict or type(item.get("start")) is not dict
                or type(item.get("extra")) is not dict):
            _fail("malformed Semgrep finding")
        level = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}.get(item["extra"].get("severity"))
        if level is None:
            _fail("unsupported Semgrep severity")
        yield item.get("check_id"), level, item.get("path"), item["start"].get("line"), item["extra"].get("message")


def _sarif(data):
    if type(data) is not dict or data.get("version") != "2.1.0":
        _fail("unsupported SARIF version")
    runs = data.get("runs")
    if type(runs) is not list or not 1 <= len(runs) <= 16:
        _fail("invalid SARIF runs")
    count = 0
    for run in runs:
        if type(run) is not dict:
            _fail("invalid SARIF run")
        for invocation in run.get("invocations", []):
            if type(invocation) is not dict or invocation.get("executionSuccessful") is False:
                _fail("SARIF scanner execution failure")
        for item in _required_list(run.get("results", []), "SARIF results"):
            count += 1
            if count > MAX_FINDINGS or type(item) is not dict:
                _fail("invalid SARIF finding count")
            locations = item.get("locations")
            if type(locations) is not list or not locations or type(locations[0]) is not dict:
                _fail("SARIF result has no physical location")
            physical = locations[0].get("physicalLocation")
            if type(physical) is not dict:
                _fail("malformed SARIF physical location")
            artifact, region = physical.get("artifactLocation"), physical.get("region")
            message = item.get("message")
            if (type(artifact) is not dict or type(region) is not dict or type(message) is not dict
                    or artifact.get("uriBaseId") is not None):
                _fail("malformed SARIF location or message")
            level = {"error": "high", "warning": "medium", "note": "low", "none": "info"}.get(
                item.get("level", "warning"))
            if level is None:
                _fail("unsupported SARIF severity")
            yield item.get("ruleId"), level, artifact.get("uri"), region.get("startLine"), message.get("text")


ADAPTERS = {"ruff-json": _ruff, "bandit-json": _bandit,
            "semgrep-json": _semgrep, "sarif-2.1.0": _sarif}


def _id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:24]


def normalize_report(root: Path, reviewer, stdout: bytes, raw_sha256: str, snapshot: tuple):
    """Validate one wrapper envelope and derive a bounded, deterministic verdict."""
    try:
        data = json.loads(stdout.decode("utf-8", "strict"),
                          object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Abort("REVIEW_REPORT_INVALID: wrapper stdout must be UTF-8 JSON") from exc
    _bounded_tree(data)
    if (type(data) is not dict or set(data) != {"schema_version", "tools"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or type(data["tools"]) is not list or len(data["tools"]) > 16):
        _fail("unsupported scanner envelope")
    policy = {item.id: item for item in reviewer.scanners}
    if not policy:
        _fail("no configured scanners")
    found = set()
    tool_results = []
    findings = {}
    total = 0
    for report in data["tools"]:
        if (type(report) is not dict or set(report) - {"id", "status", "format", "report"}
                or not {"id", "status", "format"} <= set(report)):
            _fail("invalid tool envelope")
        name = report["id"]
        if type(name) is not str or name not in policy or name in found:
            _fail("unexpected or duplicate tool identity")
        found.add(name)
        spec = policy[name]
        status = report["status"]
        if (type(status) is not str or status not in STATUSES
                or type(report["format"]) is not str or report["format"] != spec.format):
            _fail("scanner format or status mismatch")
        if status in {"FAILED", "TIMED_OUT", "UNKNOWN"}:
            if "report" in report and report["report"] is not None:
                _fail("incomplete scanner must not publish findings")
            tool_results.append({"id": name, "status": status, "required": spec.required,
                                 "format": spec.format, "finding_count": 0})
            continue
        if "report" not in report:
            _fail("successful scanner is missing its report")
        entries = list(ADAPTERS[spec.format](report["report"]))
        if (status == "SUCCEEDED" and entries) or (status == "FINDINGS" and not entries):
            _fail("scanner status contradicts parsed findings")
        total += len(entries)
        if total > MAX_FINDINGS:
            _fail("too many findings")
        tool_results.append({"id": name, "status": status, "required": spec.required,
                             "format": spec.format, "finding_count": len(entries)})
        for position, (rule, severity, path, line, message) in enumerate(entries):
            rule = _short(rule, "rule", 128)
            message = _short(message, "finding message")
            path = _path(root, path)
            line = _line(line)
            key = (path, line, message.strip().casefold())
            provenance = {"tool": name, "rule": rule, "index": position,
                          "source_id": _id(name, rule, path, line, message)}
            if key not in findings:
                findings[key] = {"id": _id(path, line, message.strip().casefold()),
                                 "path": path, "line": line, "message": message,
                                 "severity": severity, "sources": [provenance]}
            else:
                item = findings[key]
                item["sources"].append(provenance)
                if SEVERITY_ORDER[severity] > SEVERITY_ORDER[item["severity"]]:
                    item["severity"] = severity
    for spec in reviewer.scanners:
        if spec.id not in found:
            tool_results.append({"id": spec.id, "status": "UNKNOWN", "required": spec.required,
                                 "format": spec.format, "finding_count": 0})
    tool_results.sort(key=lambda item: item["id"])
    ordered = sorted(findings.values(), key=lambda item: (
        -SEVERITY_ORDER[item["severity"]], item["path"], item["line"], item["id"]))
    for item in ordered:
        item["sources"].sort(key=lambda src: (src["tool"], src["rule"], src["index"]))
    unknown_required = any(item["required"] and item["status"] not in {"SUCCEEDED", "FINDINGS"}
                           for item in tool_results)
    blocked = any(SEVERITY_ORDER[item["severity"]] >= SEVERITY_ORDER["high"]
                  and any(policy[src["tool"]].required for src in item["sources"])
                  for item in ordered)
    verdict = "ESCALATE" if unknown_required else "CHANGES_REQUIRED" if blocked else "PASS"
    return {"schema_version": 1, "reviewer_id": reviewer.id, "snapshot": list(snapshot),
            "raw_stdout_sha256": raw_sha256, "verdict": verdict,
            "tools": tool_results, "findings": ordered,
            "findings_total": total, "findings_unique": len(ordered)}
