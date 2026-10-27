"""Pure reconciliation rules for recorded patch history and verified audit facts."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, cast

from .core.contracts import GitHubPr, StateDocument, WorkflowRecord
from .model import Abort, BASENAME_PATTERN
from .patch_history import HistoryEntry, parse_history


SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}
PHASES = ("new", "branch_created", "applying", "patch_applied", "verified",
          "committed", "pushed", "pr_created", "merged", "synced")


@dataclass(frozen=True)
class Finding:
    severity: str
    confidence: str
    patch: str
    code: str
    source: str
    detail: str
    recommendation: str


@dataclass(frozen=True)
class RunEvidence:
    patch: str
    outcome: str
    action_code: str


@dataclass(frozen=True)
class AuditGroups:
    workflows: dict[str, tuple[WorkflowRecord, ...]]
    runs: dict[str, tuple[RunEvidence, ...]]
    patches: tuple[str, ...]
    findings: tuple[Finding, ...]


def safe_label(value: object) -> str:
    """Sanitize and bound historical identifiers in rendered findings."""
    return re.sub(r"[\x00-\x1f\x7f]", "?", str(value))[:140]


def finding(
    severity: str, confidence: str, patch: str, code: str,
    source: str, detail: str, recommendation: str,
) -> Finding:
    return Finding(
        severity, confidence, safe_label(patch), code, source,
        safe_label(detail) if len(detail) > 500 else
        re.sub(r"[\x00-\x1f\x7f]", "?", detail), recommendation,
    )


def parse_created_entries(
    contents: str | None, source: Path,
) -> tuple[tuple[str, ...] | None, tuple[Finding, ...]]:
    """Interpret registry lines without opening a path or changing the journal."""
    if contents is None:
        return None, ()
    names: list[str] = []
    seen: set[str] = set()
    findings: list[Finding] = []
    for line, name in enumerate(contents.splitlines(), start=1):
        if not BASENAME_PATTERN.fullmatch(name):
            findings.append(finding(
                "ERROR", "CONFLICT", "-", "INVALID_CREATED_ENTRY", str(source),
                f"Invalid patch name at line {line}",
                "Repair the registry after verifying the original generation history."))
            continue
        if name in seen:
            findings.append(finding(
                "ERROR", "CONFLICT", name, "DUPLICATE_CREATED", str(source),
                f"Duplicate name at line {line}",
                "Reconcile duplicate basenames without silently renaming history."))
        names.append(name)
        seen.add(name)
    return tuple(names), tuple(findings)


def parse_applied_entries(
    contents: str | None, source: Path,
) -> tuple[tuple[HistoryEntry, ...], tuple[Finding, ...]]:
    """Treat malformed applied history as a finding without rewriting it."""
    if contents is None:
        return (), ()
    try:
        return parse_history(contents), ()
    except Abort as exc:
        return (), (finding(
            "ERROR", "CONFLICT", "-", "INVALID_APPLIED_HISTORY", str(source), str(exc),
            "Inspect and recover the applied-patch journal manually."),)


def group_audit_records(
    state: StateDocument, repository: str, state_source: Path,
    created: tuple[str, ...] | None, applied_names: tuple[str, ...],
) -> AuditGroups:
    """Group validated stored identities; no Git calls or inferred completion."""
    workflows: dict[str, list[WorkflowRecord]] = defaultdict(list)
    runs: dict[str, list[RunEvidence]] = defaultdict(list)
    findings: list[Finding] = []
    for record in state["workflows"].values():
        if not isinstance(record, dict) or record.get("repository") != repository:
            continue
        patch = record.get("patch_file")
        if isinstance(patch, str) and BASENAME_PATTERN.fullmatch(patch):
            workflows[patch].append(record)
        else:
            findings.append(finding(
                "ERROR", "CONFLICT", "-", "INVALID_WORKFLOW_ID", str(state_source),
                "Workflow has no safe patch identity", "Inspect the stored workflow identity."))
    for run in state.get("operation_runs", []):
        if run["repository"] == repository:
            action = cast(dict[str, object], run["operation"])
            runs[str(run["patch"])].append(RunEvidence(
                str(run["patch"]), str(run["outcome"]), str(action["code"])))
    patches = tuple(dict.fromkeys((*(created or ()), *applied_names, *workflows, *runs)))
    return AuditGroups(
        {name: tuple(items) for name, items in workflows.items()},
        {name: tuple(items) for name, items in runs.items()},
        patches, tuple(findings),
    )


def reconcile_patch_history(
    created: tuple[str, ...] | None, applied_names: tuple[str, ...],
    created_source: Path, applied_source: Path,
) -> tuple[Finding, ...]:
    """Compare generation and application order without external state."""
    findings: list[Finding] = []
    applied_set = set(applied_names)
    for patch, count in Counter(applied_names).items():
        if count > 1:
            findings.append(finding(
                "ERROR", "CONFLICT", patch, "DUPLICATE_APPLIED", str(applied_source),
                f"{count} applications use one basename",
                "Verify the distinct ZIP bytes and reconcile history manually."))
    if created is None:
        findings.append(finding(
            "INFO", "UNKNOWN", "-", "NO_CREATED_REGISTRY", str(created_source),
            "Generation order cannot be verified",
            "Provide a complete append-only registry when available."))
        return tuple(findings)

    created_set = set(created)
    seen_applied: set[str] = set()
    positions: dict[str, int] = {}
    for index, name in enumerate(created):
        positions.setdefault(name, index)
    expected_prefix = 0
    for name in applied_names:
        if name not in created_set:
            findings.append(finding(
                "WARNING", "CONFLICT", name, "UNREGISTERED_APPLIED", str(applied_source),
                "Applied patch absent from generation registry",
                "Verify registry completeness and patch identity."))
            continue
        missing_before: list[str] = []
        cursor = expected_prefix
        while cursor < positions[name] and len(missing_before) < 5:
            predecessor = created[cursor]
            if predecessor not in seen_applied and predecessor not in missing_before:
                missing_before.append(predecessor)
            cursor += 1
        if missing_before:
            findings.append(finding(
                "ERROR", "CONFLICT", name, "OUT_OF_ORDER",
                "created_patches.txt + applied_patches.txt",
                "Applied before earlier patch(es): " + ", ".join(missing_before),
                "Inspect actual patch content and restore correct history manually."))
        seen_applied.add(name)
        while expected_prefix < len(created) and created[expected_prefix] in seen_applied:
            expected_prefix += 1
    for name in dict.fromkeys(created):
        if name not in applied_set:
            findings.append(finding(
                "WARNING", "RECORDED", name, "MISSING_APPLICATION",
                "created_patches.txt + applied_patches.txt",
                "Registered patch has no successful application record",
                "Apply the missing patch only after inspecting the worktree and predecessors."))
    return tuple(findings)


def reconcile_workflow_records(
    groups: AuditGroups, applied_names: tuple[str, ...],
    state_source: Path, base: str,
    branch_present: Mapping[str, bool], commit_present: Mapping[str, bool],
) -> tuple[tuple[Finding, ...], dict[str, tuple[str, ...]]]:
    """Reconcile checkpoints and journal attempts with already collected local facts."""
    findings: list[Finding] = []
    facts: dict[str, list[str]] = {}
    applied_set = set(applied_names)
    for name in groups.patches:
        records = groups.workflows.get(name, ())
        patch_facts: list[str] = []
        for record in records:
            actual = record.get("applied_branch") or record.get("branch")
            if isinstance(actual, str):
                patch_facts.append("local-branch=" + (
                    "VERIFIED" if branch_present.get(actual, False) else "UNKNOWN"))
            commit = record.get("commit_sha")
            if isinstance(commit, str):
                patch_facts.append("local-commit=" + (
                    "VERIFIED" if commit_present.get(commit, False) else "CONFLICT"))
            if record.get("pushed_sha") or record.get("pr_number"):
                patch_facts.append("remote=UNKNOWN")
        facts[name] = patch_facts

        if len(records) > 1:
            findings.append(finding(
                "WARNING", "CONFLICT", name, "AMBIGUOUS_WORKFLOWS", str(state_source),
                f"{len(records)} workflow identities share this basename",
                "Inspect feature branches and patch digests before selecting a workflow."))
        for record in records:
            phase = record.get("phase", "new")
            if phase not in PHASES:
                findings.append(finding(
                    "ERROR", "CONFLICT", name, "INVALID_PHASE", str(state_source),
                    f"Unknown workflow phase: {phase}",
                    "Inspect the checkpoint without rewriting it."))
                continue
            if phase == "applying":
                findings.append(finding(
                    "ERROR", "UNKNOWN", name, "INTERRUPTED_APPLICATION", str(state_source),
                    "Application checkpoint is incomplete",
                    "Inspect backups and worktree before retrying APL."))
            elif phase not in {"new", "synced"}:
                findings.append(finding(
                    "WARNING", "RECORDED", name, "UNFINISHED_WORKFLOW", str(state_source),
                    f"Last checkpoint: {phase}",
                    "Inspect 10 [STS] and continue only verified remaining actions."))
            if phase in PHASES[3:] and name not in applied_set:
                findings.append(finding(
                    "ERROR", "CONFLICT", name, "APPLIED_CHECKPOINT_WITHOUT_HISTORY",
                    str(state_source), "Applied phase exists without journal entry",
                    "Reconcile actual extraction evidence and applied journal manually."))
            actual = record.get("applied_branch") or record.get("branch")
            if (isinstance(actual, str) and actual != base
                    and phase in PHASES[1:] and not branch_present.get(actual, False)):
                level = "INFO" if phase == "synced" else "ERROR"
                confidence = "UNKNOWN" if phase == "synced" else "CONFLICT"
                findings.append(finding(
                    level, confidence, name, "MISSING_LOCAL_BRANCH",
                    "local Git refs + state", f"Recorded branch not found: {actual}",
                    "Inspect local and remote refs before recreating a branch."))
            commit_sha = record.get("commit_sha")
            if commit_sha and not commit_present.get(commit_sha, False):
                findings.append(finding(
                    "ERROR", "CONFLICT", name, "MISSING_LOCAL_COMMIT",
                    "local Git objects + state", "Recorded commit is absent locally",
                    "Recover the correct commit or inspect repository history."))
            elif phase in PHASES[5:] and not commit_sha:
                findings.append(finding(
                    "WARNING", "UNKNOWN", name, "COMMIT_NOT_RECORDED", str(state_source),
                    "Published phase lacks local commit identity",
                    "Inspect Git and history; do not assume a unique patch commit."))
            if phase in PHASES[6:] and not record.get("pushed_sha"):
                findings.append(finding(
                    "WARNING", "UNKNOWN", name, "PUSH_NOT_RECORDED", str(state_source),
                    "Later workflow phase lacks a pushed SHA",
                    "Verify the remote branch and publication evidence before continuing."))
            if phase in PHASES[7:] and record.get("pr_number") is None:
                findings.append(finding(
                    "WARNING", "UNKNOWN", name, "PR_NOT_RECORDED", str(state_source),
                    "Later workflow phase lacks a PR number",
                    "Inspect historical pull requests without assuming a merge."))
            if phase == "synced" and not record.get("local_base_head"):
                findings.append(finding(
                    "INFO", "UNKNOWN", name, "SYNC_NOT_RECORDED", str(state_source),
                    "No local base synchronization checkpoint",
                    "Verify the base ref and merged PR before relying on synced status."))
        for run in groups.runs.get(name, ()):
            if run.outcome in {"STARTED", "INDETERMINATE", "INTERRUPTED"}:
                findings.append(finding(
                    "WARNING", "UNKNOWN", name, "UNRESOLVED_OPERATION", "operation_runs",
                    f"{run.action_code} ended as {run.outcome}",
                    "Reconcile actual Git/GitHub effects before retrying."))
    return tuple(findings), {name: tuple(values) for name, values in facts.items()}


def reconcile_remote_evidence(
    groups: AuditGroups, patch_facts: Mapping[str, tuple[str, ...]],
    remote_heads: Mapping[str, str], prs: tuple[GitHubPr, ...],
    complete: bool, base: str,
) -> tuple[tuple[Finding, ...], dict[str, tuple[str, ...]]]:
    """Interpret a supplied remote snapshot without making remote requests."""
    findings: list[Finding] = []
    facts = {name: list(values) for name, values in patch_facts.items()}
    for name in groups.patches:
        for record in groups.workflows.get(name, ()):
            branch_name = record.get("applied_branch") or record.get("branch")
            pushed = record.get("pushed_sha")
            if not pushed:
                continue
            remote_sha = remote_heads.get(branch_name) if isinstance(branch_name, str) else None
            matching_prs = [pr for pr in prs if pr.get("headRefName") == branch_name
                            and pr.get("headRefOid") == pushed
                            and pr.get("baseRefName") == base]
            if remote_sha and remote_sha != pushed:
                facts[name].append("remote-head=CONFLICT")
                findings.append(finding(
                    "WARNING", "CONFLICT", name, "REMOTE_HEAD_DRIFT", "git ls-remote",
                    "Remote branch differs from recorded pushed SHA",
                    "Inspect remote history before pushing or merging."))
            elif not remote_sha and not any(pr.get("state") == "MERGED" for pr in matching_prs):
                findings.append(finding(
                    "WARNING", "UNKNOWN", name, "REMOTE_BRANCH_ABSENT", "git ls-remote",
                    "No matching remote branch or confirmed merged PR",
                    "Inspect deleted remote refs and historical PRs."))
            elif remote_sha == pushed:
                facts[name].append("remote-head=VERIFIED")
            if record.get("pr_number") is not None and complete:
                match = [pr for pr in matching_prs if pr.get("number") == record["pr_number"]]
                if not match:
                    facts[name].append("pull-request=CONFLICT")
                    findings.append(finding(
                        "ERROR", "CONFLICT", name, "PR_REVISION_MISMATCH",
                        "GitHub PR listing + state",
                        "Recorded PR does not match the pushed revision",
                        "Verify PR number and source commit before publication actions."))
                elif record.get("phase") in {"merged", "synced"} and not (
                        match[0].get("state") == "MERGED" and match[0].get("mergedAt")):
                    findings.append(finding(
                        "ERROR", "CONFLICT", name, "MERGE_NOT_CONFIRMED",
                        "GitHub PR listing + state", "Recorded merge lacks live GitHub confirmation",
                        "Inspect the PR before considering the workflow complete."))
                elif match[0].get("state") == "MERGED" and match[0].get("mergedAt"):
                    facts[name].append("pull-request=VERIFIED")
    return tuple(findings), {name: tuple(values) for name, values in facts.items()}


def finalize_patch_facts(
    patch_facts: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Drop a remote-unknown hint only after affirmative remote evidence."""
    verified = {"remote-head=VERIFIED", "pull-request=VERIFIED"}
    return {
        name: tuple(value for value in values if value != "remote=UNKNOWN")
        if any(value in verified for value in values) else tuple(values)
        for name, values in patch_facts.items()
    }
