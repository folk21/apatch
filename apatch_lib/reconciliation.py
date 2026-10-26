"""Read-only reconciliation of project-local patch history and optional GitHub facts."""

import os
import re
import stat
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import github
from .created_patches import MAX_REGISTRY_BYTES, registry_path
from .model import Abort, BASENAME_PATTERN
from .patch_history import MAX_HISTORY_BYTES, parse_history
from .state import read_state_snapshot
from .status import _branch_present, _commit_present, local_branch, local_repository


MAX_DISPLAY_FINDINGS = 100
MAX_DISPLAY_PATCHES = 100
MAX_REMOTE_PRS = 500
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
class AuditReport:
    root: Path
    created: tuple[str, ...] | None
    applied: tuple[str, ...]
    patches: tuple[str, ...]
    workflows: dict
    head: str
    branch: str
    dirty_count: int
    remote_coverage: str
    patch_facts: dict[str, tuple[str, ...]]
    findings: tuple[Finding, ...]


def _safe_text(path: Path, limit: int) -> str | None:
    """Never follow runtime-file symlinks or create a missing history file."""
    parent = path.parent
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
        raise Abort(f"Unsafe audit source directory: {parent}")
    if path.is_symlink():
        raise Abort(f"Audit source must not be a symlink: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Abort(f"Cannot open audit source {path}: {exc}") from exc
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise Abort(f"Audit source is not a regular file within size limit: {path}")
            raw = handle.read(limit + 1)
            if len(raw) > limit:
                raise Abort(f"Audit source exceeds size limit: {path}")
        return raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise Abort(f"Cannot read UTF-8 audit source {path}: {exc}") from exc


def _git(root: Path, *args, timeout=10):
    """Run strictly read-only Git commands without locks or repository writes."""
    try:
        completed = subprocess.run(["git", *args], cwd=root, text=True,
                                   capture_output=True, timeout=timeout, check=False,
                                   env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Abort(f"Local Git inspection failed: {args[0]}: {type(exc).__name__}") from exc
    if completed.returncode:
        raise Abort(f"Local Git inspection failed: {args[0]} (exit {completed.returncode})")
    return completed.stdout


def _label(value):
    """Bound and sanitize historical identifiers before displaying them."""
    return re.sub(r"[\x00-\x1f\x7f]", "?", str(value))[:140]


def _finding(severity, confidence, patch, code, source, detail, recommendation):
    return Finding(severity, confidence, _label(patch), code, source,
                   _label(detail) if len(detail) > 500 else
                   re.sub(r"[\x00-\x1f\x7f]", "?", detail), recommendation)


def _created_entries(root, findings):
    source = registry_path(root)
    contents = _safe_text(source, MAX_REGISTRY_BYTES)
    if contents is None:
        return None
    names = []
    seen = set()
    for line, name in enumerate(contents.splitlines(), start=1):
        if not BASENAME_PATTERN.fullmatch(name):
            findings.append(_finding("ERROR", "CONFLICT", "-", "INVALID_CREATED_ENTRY",
                                     str(source), f"Invalid patch name at line {line}",
                                     "Repair the registry after verifying the original generation history."))
            continue
        if name in seen:
            findings.append(_finding("ERROR", "CONFLICT", name, "DUPLICATE_CREATED",
                                     str(source), f"Duplicate name at line {line}",
                                     "Reconcile duplicate basenames without silently renaming history."))
        names.append(name)
        seen.add(name)
    return tuple(names)


def _applied_entries(path, findings):
    contents = _safe_text(path, MAX_HISTORY_BYTES)
    if contents is None:
        return ()
    try:
        return tuple(parse_history(contents))
    except Abort as exc:
        findings.append(_finding("ERROR", "CONFLICT", "-", "INVALID_APPLIED_HISTORY",
                                 str(path), str(exc),
                                 "Inspect and recover the applied-patch journal manually."))
        return ()


def _remote_snapshot(config, root):
    """Query remote state once; never fetch, checkout, or mutate local refs."""
    repo = github.repository(config, root)
    raw = github.gh_output(config, root, ["gh", "pr", "list", "--repo", repo,
                                          "--state", "all", "--limit", str(MAX_REMOTE_PRS),
                                          "--json", "number,state,headRefName,baseRefName,headRefOid,mergedAt"])
    prs = github.decode_pr_list(raw, expected_repo=repo, max_items=MAX_REMOTE_PRS)
    refs = _git(root, "ls-remote", "--heads", config.remote,
                timeout=config.github_timeout_seconds)
    heads = {}
    for line in refs.splitlines():
        sha, sep, ref = line.partition("\t")
        if sep and re.fullmatch(r"[a-f0-9]{40}", sha) and ref.startswith("refs/heads/"):
            heads[ref.removeprefix("refs/heads/")] = sha
    return heads, prs, len(prs) < MAX_REMOTE_PRS


def audit_repository(root: Path, config, *, verify_remote=False) -> AuditReport:
    """Correlate recorded claims and live read-only evidence without repairing anything."""
    local_repository(root)
    branch = local_branch(root)
    current_head = _git(root, "rev-parse", "HEAD").strip()
    dirty_count = len(_git(root, "status", "--porcelain", "--untracked-files=all").splitlines())
    findings = []
    created = _created_entries(root, findings)
    entries = _applied_entries(config.applied_patches_path, findings)
    state = read_state_snapshot(config.state_path)
    repository = str(root.resolve())
    workflows = defaultdict(list)
    for record in state["workflows"].values():
        if not isinstance(record, dict) or record.get("repository") != repository:
            continue
        patch = record.get("patch_file")
        if isinstance(patch, str) and BASENAME_PATTERN.fullmatch(patch):
            workflows[patch].append(record)
        else:
            findings.append(_finding("ERROR", "CONFLICT", "-", "INVALID_WORKFLOW_ID",
                                     str(config.state_path), "Workflow has no safe patch identity",
                                     "Inspect the stored workflow identity."))
    runs = defaultdict(list)
    for run in state.get("operation_runs", []):
        if run["repository"] == repository:
            runs[run["patch"]].append(run)
    created_set = set(created or ())
    applied_names = tuple(entry.patch for entry in entries)
    applied_set = set(applied_names)
    patches = tuple(dict.fromkeys((* (created or ()), *applied_names, *workflows, *runs)))
    patch_facts = {}
    branch_cache = {}
    commit_cache = {}
    for name in patches:
        facts = []
        for record in workflows[name]:
            actual = record.get("applied_branch") or record.get("branch")
            if isinstance(actual, str):
                if actual not in branch_cache:
                    branch_cache[actual] = _branch_present(root, actual)
                facts.append("local-branch=" + ("VERIFIED" if branch_cache[actual] else "UNKNOWN"))
            commit = record.get("commit_sha")
            if isinstance(commit, str):
                if commit not in commit_cache:
                    commit_cache[commit] = _commit_present(root, commit)
                facts.append("local-commit=" + ("VERIFIED" if commit_cache[commit] else "CONFLICT"))
            if record.get("pushed_sha") or record.get("pr_number"):
                facts.append("remote=UNKNOWN")
        patch_facts[name] = facts

    for patch, count in Counter(applied_names).items():
        if count > 1:
            findings.append(_finding("ERROR", "CONFLICT", patch, "DUPLICATE_APPLIED",
                                     str(config.applied_patches_path), f"{count} applications use one basename",
                                     "Verify the distinct ZIP bytes and reconcile history manually."))
    if created is None:
        findings.append(_finding("INFO", "UNKNOWN", "-", "NO_CREATED_REGISTRY",
                                 str(registry_path(root)), "Generation order cannot be verified",
                                 "Provide a complete append-only registry when available."))
    else:
        seen_applied = set()
        positions = {}
        for index, name in enumerate(created):
            positions.setdefault(name, index)
        expected_prefix = 0
        for name in applied_names:
            if name not in created_set:
                findings.append(_finding("WARNING", "CONFLICT", name, "UNREGISTERED_APPLIED",
                                         str(config.applied_patches_path), "Applied patch absent from generation registry",
                                         "Verify registry completeness and patch identity."))
                continue
            missing_before = []
            cursor = expected_prefix
            while cursor < positions[name] and len(missing_before) < 5:
                predecessor = created[cursor]
                if predecessor not in seen_applied and predecessor not in missing_before:
                    missing_before.append(predecessor)
                cursor += 1
            if missing_before:
                findings.append(_finding("ERROR", "CONFLICT", name, "OUT_OF_ORDER",
                                         "created_patches.txt + applied_patches.txt",
                                         "Applied before earlier patch(es): " + ", ".join(missing_before),
                                         "Inspect actual patch content and restore correct history manually."))
            seen_applied.add(name)
            while expected_prefix < len(created) and created[expected_prefix] in seen_applied:
                expected_prefix += 1
        for name in dict.fromkeys(created):
            if name not in applied_set:
                findings.append(_finding("WARNING", "RECORDED", name, "MISSING_APPLICATION",
                                         "created_patches.txt + applied_patches.txt",
                                         "Registered patch has no successful application record",
                                         "Apply the missing patch only after inspecting the worktree and predecessors."))

    for name in patches:
        records = workflows[name]
        if len(records) > 1:
            findings.append(_finding("WARNING", "CONFLICT", name, "AMBIGUOUS_WORKFLOWS",
                                     str(config.state_path), f"{len(records)} workflow identities share this basename",
                                     "Inspect feature branches and patch digests before selecting a workflow."))
        for record in records:
            phase = record.get("phase", "new")
            if phase not in PHASES:
                findings.append(_finding("ERROR", "CONFLICT", name, "INVALID_PHASE",
                                         str(config.state_path), f"Unknown workflow phase: {phase}",
                                         "Inspect the checkpoint without rewriting it."))
                continue
            if phase == "applying":
                findings.append(_finding("ERROR", "UNKNOWN", name, "INTERRUPTED_APPLICATION",
                                         str(config.state_path), "Application checkpoint is incomplete",
                                         "Inspect backups and worktree before retrying APL."))
            elif phase not in {"new", "synced"}:
                findings.append(_finding("WARNING", "RECORDED", name, "UNFINISHED_WORKFLOW",
                                         str(config.state_path), f"Last checkpoint: {phase}",
                                         "Inspect 10 [STS] and continue only verified remaining actions."))
            if phase in PHASES[3:] and name not in applied_set:
                findings.append(_finding("ERROR", "CONFLICT", name, "APPLIED_CHECKPOINT_WITHOUT_HISTORY",
                                         str(config.state_path), "Applied phase exists without journal entry",
                                         "Reconcile actual extraction evidence and applied journal manually."))
            actual = record.get("applied_branch") or record.get("branch")
            if (isinstance(actual, str) and actual != config.base
                    and phase in PHASES[1:] and not branch_cache.get(actual, False)):
                level = "INFO" if phase == "synced" else "ERROR"
                confidence = "UNKNOWN" if phase == "synced" else "CONFLICT"
                findings.append(_finding(level, confidence, name, "MISSING_LOCAL_BRANCH",
                                         "local Git refs + state", f"Recorded branch not found: {actual}",
                                         "Inspect local and remote refs before recreating a branch."))
            commit_sha = record.get("commit_sha")
            if commit_sha and not commit_cache.get(commit_sha, False):
                findings.append(_finding("ERROR", "CONFLICT", name, "MISSING_LOCAL_COMMIT",
                                         "local Git objects + state", "Recorded commit is absent locally",
                                         "Recover the correct commit or inspect repository history."))
            elif phase in PHASES[5:] and not commit_sha:
                findings.append(_finding("WARNING", "UNKNOWN", name, "COMMIT_NOT_RECORDED",
                                         str(config.state_path), "Published phase lacks local commit identity",
                                         "Inspect Git and history; do not assume a unique patch commit."))
            if phase in PHASES[6:] and not record.get("pushed_sha"):
                findings.append(_finding("WARNING", "UNKNOWN", name, "PUSH_NOT_RECORDED",
                                         str(config.state_path), "Later workflow phase lacks a pushed SHA",
                                         "Verify the remote branch and publication evidence before continuing."))
            if phase in PHASES[7:] and record.get("pr_number") is None:
                findings.append(_finding("WARNING", "UNKNOWN", name, "PR_NOT_RECORDED",
                                         str(config.state_path), "Later workflow phase lacks a PR number",
                                         "Inspect historical pull requests without assuming a merge."))
            if phase == "synced" and not record.get("local_base_head"):
                findings.append(_finding("INFO", "UNKNOWN", name, "SYNC_NOT_RECORDED",
                                         str(config.state_path), "No local base synchronization checkpoint",
                                         "Verify the base ref and merged PR before relying on synced status."))
        for run in runs[name]:
            if run["outcome"] in {"STARTED", "INDETERMINATE", "INTERRUPTED"}:
                findings.append(_finding("WARNING", "UNKNOWN", name, "UNRESOLVED_OPERATION",
                                         "operation_runs", f"{run['operation']['code']} ended as {run['outcome']}",
                                         "Reconcile actual Git/GitHub effects before retrying."))

    remote_coverage = "UNKNOWN (offline; use verifyRemote=true to query GitHub)"
    if verify_remote:
        try:
            remote_heads, prs, complete = _remote_snapshot(config, root)
            remote_coverage = "VERIFIED (remote refs and GitHub PR listing)" if complete else \
                              "UNKNOWN (GitHub PR listing reached its limit)"
            for name in patches:
                for record in workflows[name]:
                    branch_name = record.get("applied_branch") or record.get("branch")
                    pushed = record.get("pushed_sha")
                    if not pushed:
                        continue
                    remote_sha = remote_heads.get(branch_name)
                    matching_prs = [pr for pr in prs if pr.get("headRefName") == branch_name
                                    and pr.get("headRefOid") == pushed
                                    and pr.get("baseRefName") == config.base]
                    if remote_sha and remote_sha != pushed:
                        patch_facts[name].append("remote-head=CONFLICT")
                        findings.append(_finding("WARNING", "CONFLICT", name, "REMOTE_HEAD_DRIFT",
                                                 "git ls-remote", "Remote branch differs from recorded pushed SHA",
                                                 "Inspect remote history before pushing or merging."))
                    elif not remote_sha and not any(pr.get("state") == "MERGED" for pr in matching_prs):
                        findings.append(_finding("WARNING", "UNKNOWN", name, "REMOTE_BRANCH_ABSENT",
                                                 "git ls-remote", "No matching remote branch or confirmed merged PR",
                                                 "Inspect deleted remote refs and historical PRs."))
                    elif remote_sha == pushed:
                        patch_facts[name].append("remote-head=VERIFIED")
                    if record.get("pr_number") is not None and complete:
                        match = [pr for pr in matching_prs if pr.get("number") == record["pr_number"]]
                        if not match:
                            patch_facts[name].append("pull-request=CONFLICT")
                            findings.append(_finding("ERROR", "CONFLICT", name, "PR_REVISION_MISMATCH",
                                                     "GitHub PR listing + state", "Recorded PR does not match the pushed revision",
                                                     "Verify PR number and source commit before publication actions."))
                        elif record.get("phase") in {"merged", "synced"} and not (
                                match[0].get("state") == "MERGED" and match[0].get("mergedAt")):
                            findings.append(_finding("ERROR", "CONFLICT", name, "MERGE_NOT_CONFIRMED",
                                                     "GitHub PR listing + state", "Recorded merge lacks live GitHub confirmation",
                                                     "Inspect the PR before considering the workflow complete."))
                        elif match[0].get("state") == "MERGED" and match[0].get("mergedAt"):
                            patch_facts[name].append("pull-request=VERIFIED")
        except (Abort, ValueError, KeyError, TypeError) as exc:
            remote_coverage = f"UNKNOWN (remote verification unavailable: {type(exc).__name__})"
            findings.append(_finding("WARNING", "UNKNOWN", "-", "REMOTE_UNAVAILABLE",
                                     "GitHub + Git remote", "Remote reads could not be verified",
                                     "Retry AUD with verifyRemote=true when connectivity is restored."))

    findings.sort(key=lambda item: (SEVERITY_ORDER[item.severity], item.patch,
                                    item.code, item.source))
    for facts in patch_facts.values():
        if any(item in {"remote-head=VERIFIED", "pull-request=VERIFIED"} for item in facts):
            facts[:] = [item for item in facts if item != "remote=UNKNOWN"]
    return AuditReport(root, created, applied_names, patches, dict(workflows), current_head,
                       branch, dirty_count, remote_coverage,
                       {name: tuple(facts) for name, facts in patch_facts.items()}, tuple(findings))


def format_audit(report: AuditReport) -> str:
    """Bound console diagnostics but retain every history entry and finding in memory."""
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
    for finding in report.findings[:MAX_DISPLAY_FINDINGS]:
        lines.append(f"  {finding.severity} | {finding.confidence} | {finding.patch} | "
                     f"{finding.code} | {finding.source}")
        lines.append(f"    {finding.detail}")
        lines.append(f"    Recommendation: {finding.recommendation}")
    if len(report.findings) > MAX_DISPLAY_FINDINGS:
        lines.append(f"  ... {len(report.findings) - MAX_DISPLAY_FINDINGS} additional findings omitted from display")
    lines.append("Audit completed without modifying state, history, Git refs, or worktree.")
    return "\n".join(lines)
