"""Read-only audit orchestration over collectors and deterministic reconciliation rules."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .audit_collectors import (collect_local_evidence, local_git as _git,
                               remote_snapshot)
from .audit_rules import (
    SEVERITY_ORDER, Finding, finalize_patch_facts, group_audit_records,
    parse_applied_entries, parse_created_entries, reconcile_patch_history,
    reconcile_remote_evidence, reconcile_workflow_records, safe_label as _label,
)
from .core.contracts import GitHubPr, WorkflowRecord
from .model import Abort, Config


MAX_DISPLAY_FINDINGS = 100
MAX_DISPLAY_PATCHES = 100


def _remote_snapshot(config: Config, root: Path) -> tuple[dict[str, str], list[GitHubPr], bool]:
    """Keep the existing audit transport seam for callers and tests."""
    return remote_snapshot(config, root, git_reader=_git)


@dataclass(frozen=True)
class AuditReport:
    root: Path
    created: tuple[str, ...] | None
    applied: tuple[str, ...]
    patches: tuple[str, ...]
    workflows: dict[str, list[WorkflowRecord]]
    head: str
    branch: str
    dirty_count: int
    remote_coverage: str
    patch_facts: dict[str, tuple[str, ...]]
    findings: tuple[Finding, ...]


def audit_repository(
    root: Path, config: Config, *, verify_remote: bool = False,
) -> AuditReport:
    """Read evidence once and reconcile it without repairing state or Git refs."""
    local = collect_local_evidence(root, config)
    created, created_findings = parse_created_entries(local.created_text, local.created_source)
    entries, applied_findings = parse_applied_entries(local.applied_text, local.applied_source)
    applied_names = tuple(entry.patch for entry in entries)
    groups = group_audit_records(
        local.state, str(root.resolve()), local.state_source, created, applied_names)

    findings = [*created_findings, *applied_findings, *groups.findings]
    findings.extend(reconcile_patch_history(
        created, applied_names, local.created_source, local.applied_source))
    workflow_findings, patch_facts = reconcile_workflow_records(
        groups, applied_names, local.state_source, config.base,
        local.branch_present, local.commit_present)
    findings.extend(workflow_findings)

    remote_coverage = "UNKNOWN (offline; use verifyRemote=true to query GitHub)"
    if verify_remote:
        try:
            heads, prs, complete = _remote_snapshot(config, root)
            remote_coverage = (
                "VERIFIED (remote refs and GitHub PR listing)" if complete
                else "UNKNOWN (GitHub PR listing reached its limit)")
            remote_findings, patch_facts = reconcile_remote_evidence(
                groups, patch_facts, heads, tuple(prs), complete, config.base)
            findings.extend(remote_findings)
        except (Abort, ValueError, KeyError, TypeError) as exc:
            remote_coverage = (
                f"UNKNOWN (remote verification unavailable: {type(exc).__name__})")
            findings.append(Finding(
                "WARNING", "UNKNOWN", "-", "REMOTE_UNAVAILABLE",
                "GitHub + Git remote", "Remote reads could not be verified",
                "Retry AUD with verifyRemote=true when connectivity is restored."))

    findings.sort(key=lambda item: (SEVERITY_ORDER[item.severity], item.patch,
                                    item.code, item.source))
    return AuditReport(
        root, created, applied_names, groups.patches,
        {name: list(records) for name, records in groups.workflows.items()},
        local.head, local.branch, local.dirty_count, remote_coverage,
        finalize_patch_facts(patch_facts), tuple(findings),
    )


def format_audit(report: AuditReport) -> str:
    """Bound console diagnostics; never discard underlying evidence from the report."""
    counts = Counter(item.severity for item in report.findings)
    lines = ["\n==> PATCH AUDIT 11 [AUD] (read-only)", f"Repository: {report.root}",
             f"Local HEAD: {report.head[:12]} [VERIFIED] | Branch: {report.branch or 'DETACHED'} [VERIFIED]",
             f"Working-tree changes: {report.dirty_count} [VERIFIED]",
             f"Created registry: {len(report.created) if report.created is not None else 'ABSENT'} "
             f"| Applied entries: {len(report.applied)} | Known patches: {len(report.patches)}",
             f"Remote: {report.remote_coverage}",
             f"Findings: ERROR={counts['ERROR']} WARNING={counts['WARNING']} INFO={counts['INFO']}"]
    lines.append("\nPatch inventory:")
    for patch in report.patches[:MAX_DISPLAY_PATCHES]:
        created = (str(report.created.index(patch) + 1) if report.created is not None
                   and patch in report.created else "UNKNOWN")
        applied = str(report.applied.index(patch) + 1) if patch in report.applied else "UNKNOWN"
        phases = ",".join(str(record.get("phase", "new")) for record in report.workflows.get(patch, ()))
        evidence = "CONFLICT" if any(item.patch == patch and item.confidence == "CONFLICT"
                                     for item in report.findings) else "RECORDED" if (
                                         created != "UNKNOWN" or applied != "UNKNOWN" or phases) else "UNKNOWN"
        lines.append(f"  {_label(patch)} [{evidence}] created=#{created} applied=#{applied} "
                     f"workflow={_label(phases) if phases else 'UNKNOWN'} "
                     f"{' '.join(report.patch_facts[patch])}")
    if len(report.patches) > MAX_DISPLAY_PATCHES:
        lines.append(f"  ... {len(report.patches) - MAX_DISPLAY_PATCHES} additional patches omitted from display")
    lines.append("\nFindings (severity | confidence | patch | code | source):")
    if not report.findings:
        lines.append("  No inconsistencies detected in the available evidence.")
    for item in report.findings[:MAX_DISPLAY_FINDINGS]:
        lines.append(f"  {item.severity} | {item.confidence} | {item.patch} | "
                     f"{item.code} | {item.source}")
        lines.append(f"    {item.detail}")
        lines.append(f"    Recommendation: {item.recommendation}")
    if len(report.findings) > MAX_DISPLAY_FINDINGS:
        lines.append(f"  ... {len(report.findings) - MAX_DISPLAY_FINDINGS} additional findings omitted from display")
    lines.append("Audit completed without modifying state, history, Git refs, or worktree.")
    return "\n".join(lines)
