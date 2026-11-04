"""Build a deterministic, bounded LLM summary from verified scanner evidence."""

import hashlib
import json
import re
from collections import Counter

from .model import Abort


SEVERITY = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
HARD_SEVERITY = {"critical", "high"}


def _encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _changed_lines(diff):
    """Identify added lines from Git's text diff; never treat diff text as instructions."""
    changed = set()
    excerpts = []
    path = None
    line = None
    for text in diff.splitlines():
        if text.startswith("+++ b/"):
            path = text[6:]
            line = None
        elif text.startswith("@@ "):
            match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", text)
            line = int(match.group(1)) if match else None
        elif text.startswith("diff --git ") or text.startswith("=== UNTRACKED FILE:"):
            path = None
            line = None
        elif line is not None and path is not None:
            if text.startswith("+") and not text.startswith("+++"):
                changed.add((path, line))
                excerpts.append((path, line, text[1:]))
                line += 1
            elif text.startswith(" "):
                line += 1
            elif text.startswith("-") or text.startswith("\\"):
                pass
            else:
                line = None
    return changed, excerpts


def build_review_context(reports, snapshot, diff, max_bytes, *, include_messages=False,
                         include_diff=False):
    """Return a size-bounded JSON document; never silently omit high findings."""
    if not reports:
        raise Abort("REVIEW_CONTEXT_INCOMPLETE: No structured scanner evidence before LLM")
    fingerprint = hashlib.sha256(_encode(list(snapshot))).hexdigest()
    tools = []
    findings = []
    counts = Counter()
    for report in reports:
        if (report.get("schema_version") != 1 or report.get("snapshot") != list(snapshot)
                or report.get("verdict") != "PASS"):
            raise Abort("REVIEW_CONTEXT_INCOMPLETE: Scanner evidence is stale or not PASS")
        reviewer = report["reviewer_id"]
        for tool in report["tools"]:
            tools.append({"reviewer": reviewer, "id": tool["id"], "status": tool["status"],
                          "required": tool["required"], "finding_count": tool["finding_count"]})
            if tool["required"] and tool["status"] not in {"SUCCEEDED", "FINDINGS"}:
                raise Abort("REVIEW_CONTEXT_INCOMPLETE: A required scanner is incomplete")
        for finding in report["findings"]:
            if finding["severity"] not in SEVERITY:
                raise Abort("REVIEW_CONTEXT_INCOMPLETE: Unrecognized severity")
            counts[finding["severity"]] += 1
            item = {"id": finding["id"], "reviewer": reviewer,
                    "severity": finding["severity"], "path": finding["path"],
                    "line": finding["line"],
                    "rules": sorted({src["rule"] for src in finding["sources"]}),
                    "scanners": sorted({src["tool"] for src in finding["sources"]})}
            if include_messages:
                item["message"] = finding["message"][:400]
            findings.append(item)
    tools.sort(key=lambda item: (item["reviewer"], item["id"]))
    changed, diff_excerpts = _changed_lines(diff)
    findings.sort(key=lambda item: (-SEVERITY[item["severity"]],
                                    (item["path"], item["line"]) not in changed,
                                    item["path"], item["line"], item["reviewer"], item["id"]))
    document = {"schema_version": 1, "snapshot_sha256": fingerprint, "head": snapshot[1],
                "tools": tools, "severity_counts": {s: counts[s] for s in SEVERITY},
                "findings_total": len(findings), "findings_omitted": 0,
                "diff_lines_omitted": 0, "truncated": False,
                "findings": [], "diff_excerpts": []}
    if len(_encode(document)) > max_bytes:
        raise Abort("REVIEW_CONTEXT_TOO_LARGE: Required scanner status exceeds context budget")
    for item in findings:
        candidate = {**document, "findings": document["findings"] + [item]}
        if len(_encode(candidate)) <= max_bytes:
            document = candidate
        elif item["severity"] in HARD_SEVERITY:
            raise Abort("REVIEW_CONTEXT_TOO_LARGE: Severe findings exceed context budget")
        else:
            document["findings_omitted"] += 1
            document["truncated"] = True
    if include_diff:
        ranks = {(f["path"], f["line"]) for f in findings}
        diff_excerpts.sort(key=lambda item: (item[0], item[1]) not in ranks)
        for path, line, source in diff_excerpts:
            excerpt = {"path": path[:512], "line": line, "text": source[:300]}
            candidate = {**document, "diff_excerpts": document["diff_excerpts"] + [excerpt]}
            if len(_encode(candidate)) <= max_bytes:
                document = candidate
            else:
                document["diff_lines_omitted"] += 1
                document["truncated"] = True
    if len(_encode(document)) > max_bytes:
        raise Abort("REVIEW_CONTEXT_TOO_LARGE: Context budget exceeded")
    return document, _encode(document)
