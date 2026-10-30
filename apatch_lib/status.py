"""Read-only, offline evidence and next-action guidance for a patch cycle."""

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .action_applicability import ActionFacts, action_unavailable
from .console import next_action_label
from .core.enums import WorkflowPhase
from .gitutil import worktree_fingerprint
from .model import Abort, BRANCH_PATTERN


PHASE_ORDER = tuple(phase.value for phase in WorkflowPhase)
ACTION_NAMES = {
    1: ("BRN", "Prepare the feature branch"),
    3: ("APL", "Apply the patch"),
    4: ("CHK", "Run canonical checks"),
    5: ("CMT", "Commit verified changes"),
    6: ("PSH", "Push the recorded commit"),
    7: ("PR", "Create or find the pull request"),
    8: ("MRG", "Merge the pull request after GitHub policy checks"),
    9: ("SYN", "Synchronize the local base branch"),
    13: ("REV", "Run required independent code review"),
}


@dataclass(frozen=True)
class StatusFact:
    value: str
    evidence: str
    detail: str = ""


@dataclass(frozen=True)
class PatchStatus:
    patch: str
    planned_branch: str
    phase: str
    current_branch: str
    facts: dict[str, StatusFact]
    next_action: int | None
    alternate_action: int | None
    guidance: str


def _git(root: Path, *args):
    """Run bounded, local-only Git inspection without emitting a network request."""
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                text=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Abort(f"Cannot inspect local Git state: {exc}") from exc
    if result.returncode not in {0, 1}:
        raise Abort(f"Local Git inspection failed: git {args[0]} (exit {result.returncode})")
    return result


def local_repository(root: Path):
    result = _git(root, "rev-parse", "--show-toplevel")
    actual = Path(result.stdout.strip()).resolve() if result.returncode == 0 else None
    if actual != root.resolve():
        raise Abort(f"Run from the Git repository root: {root}")


def local_branch(root: Path):
    return _git(root, "branch", "--show-current").stdout.strip()


def _branch_present(root: Path, name: str):
    if not BRANCH_PATTERN.fullmatch(name) and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", name):
        return False
    return _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0


def _commit_present(root: Path, sha):
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
        return False
    return _git(root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").returncode == 0


def workflow_key(root: Path, branch: str, patch: str):
    return hashlib.sha256(f"{root.resolve()}\0{branch}\0{patch}".encode()).hexdigest()


def select_record(root: Path, state: dict, handoff=None, *, patch=None):
    """Select a handoff identity or an unambiguous stored local workflow."""
    if handoff is not None:
        if patch is not None and patch != handoff.patch:
            raise Abort("--patch does not match the supplied handoff JSON")
        return state["workflows"].get(workflow_key(root, handoff.branch, handoff.patch), {}), handoff.patch, handoff.branch
    candidates = [record for record in state["workflows"].values()
                  if isinstance(record, dict) and record.get("repository") == str(root.resolve())]
    if patch is not None:
        candidates = [record for record in candidates if record.get("patch_file") == patch]
    else:
        active = local_branch(root)
        active_records = [record for record in candidates if
                          record.get("applied_branch", record.get("branch")) == active]
        if len(active_records) == 1:
            candidates = active_records
        elif len(active_records) > 1:
            candidates = active_records
    if not candidates:
        raise Abort("No stored patch workflow matches this repository. Provide the handoff JSON or --patch=NAME.zip")
    if len(candidates) > 1:
        labels = ", ".join(sorted(f"{item.get('patch_file')} ({item.get('branch')})" for item in candidates))
        raise Abort("Ambiguous patch workflow: " + labels + ". Provide a specific handoff JSON or --patch=NAME.zip")
    record = candidates[0]
    return record, record.get("patch_file", "UNKNOWN"), record.get("branch", "UNKNOWN")


def _fact(value, evidence, detail=""):
    return StatusFact(str(value), evidence, detail)


def recommend_next_action(phase: str, mode: str, branch: str, planned_branch: str,
                          *, conflict=False, dirty=False, base="main",
                          zip_pending_branch=False, zip_selected=False,
                          applied_branch: str | None = None,
                          require_patch_feature_branch=False,
                          stale_verification=False, missing_review=False):
    """Provide cautious guidance; this never replaces a command's live guards."""
    facts = ActionFacts(
        mode=mode, phase=phase, branch=branch, planned_branch=planned_branch,
        applied_branch=applied_branch or planned_branch, base=base, clean=not dirty,
        zip_selected=zip_selected, zip_first=zip_pending_branch,
        zip_pending_branch=zip_pending_branch,
        require_patch_feature_branch=require_patch_feature_branch)

    def blocked(action: int) -> str | None:
        return action_unavailable(action, facts)

    if conflict or phase == "applying":
        return None, None, "Inspect or reconcile the conflicting/interrupted workflow before continuing."
    if phase == "synced":
        return None, None, "Workflow completed; no further lifecycle operation is needed."
    if phase == WorkflowPhase.NEW:
        if zip_selected:
            if dirty or branch not in {base, planned_branch}:
                return None, None, "Review existing changes and the intended checkout before ZIP-first APL."
            if blocked(3):
                return None, None, "The selected ZIP cannot be applied from the current Git checkout."
            return 3, None, "Apply the verified new ZIP before creating its feature branch."
        if mode == "strict" and branch == planned_branch and not blocked(3):
            return 3, None, "Verify live guards before applying."
        if mode == "strict" and (branch != base or dirty):
            return None, None, "STRICT branch creation requires a clean worktree on the base branch."
        if blocked(1):
            return None, None, "Inspect the checkout before preparing a feature branch."
        return 1, 3 if mode != "strict" else None, "Select the intended branch before applying."
    if phase == WorkflowPhase.BRANCH_CREATED:
        if mode == "strict" and branch != planned_branch:
            return None, None, (
                "The prepared feature branch is not checked out; review the intended "
                "patch destination before explicitly choosing APL.")
        if blocked(3):
            return None, None, "STRICT patch application requires a compatible branch and clean worktree."
        return 3, None, "Check the selected ZIP and target branch before applying."
    if phase == WorkflowPhase.PATCH_APPLIED:
        if zip_pending_branch:
            if branch != base:
                return None, None, "Return to the recorded ZIP-first base checkout before BRN recovery."
            return 1, None, "Move the uncommitted ZIP changes from the base branch to the planned feature branch."
        if blocked(4):
            return None, None, "Reconcile the recorded patch checkout before verification."
        return 4, 3 if mode == "loose" else None, "Verify the current changed bytes before commit."
    if phase == "verified":
        if stale_verification:
            if blocked(4):
                return None, None, "Verification evidence is stale; reconcile the checkout before CHK."
            return 4, None, "Working-tree bytes or revision changed since verification; rerun CHK."
        if missing_review:
            return 13, None, "Independent review is required for the current checked bytes before CMT."
        if blocked(5):
            return None, None, "Publishing requires the verified planned feature branch."
        return 5, 3 if mode == "loose" else None, "Check the planned commit scope and message."
    if phase == "committed":
        if blocked(6):
            return None, None, "Recorded commit cannot be pushed from this checkout."
        return 6, None, "Push only after checking the recorded commit and remote branch."
    if phase == "pushed":
        if blocked(7):
            return None, None, "PR creation requires the recorded pushed feature branch checkout."
        return 7, None, "GitHub PR discovery and creation require network access."
    if phase == "pr_created":
        if blocked(8):
            return None, None, "PR merge requires the recorded feature branch checkout."
        return 8, None, "Merge requires live GitHub review and CI policy checks."
    if phase == "merged":
        if blocked(9):
            return None, None, "Local base synchronization requires a confirmed merge checkpoint."
        return 9, None, "Confirm remote merge and synchronize the local base branch."
    return None, None, "No reliable next action can be inferred from this checkpoint."


def inspect_patch(root: Path, config, record: dict, patch: str,
                  planned_branch: str, mode: str, *, zip_selected: bool = False):
    """Compare stored claims with local facts; never query GitHub or change state."""
    if not isinstance(record, dict):
        raise Abort("Invalid stored workflow record")
    phase = record.get("phase", WorkflowPhase.NEW.value)
    if phase not in PHASE_ORDER:
        raise Abort(f"Unknown stored workflow phase: {phase}")
    current = local_branch(root)
    head_result = _git(root, "rev-parse", "HEAD")
    current_head = head_result.stdout.strip()
    dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=all").stdout)
    index = PHASE_ORDER.index(phase)
    actual = record.get("applied_branch") or record.get("branch") or planned_branch
    origin = record.get("branch_origin")
    branch_present = _branch_present(root, actual)
    facts = {
        "Current branch": _fact(current or "DETACHED", "VERIFIED"),
        "Configured base": _fact(config.base, "CONFIG", f"source: {config.base_branch_source}"),
        "Actual patch branch": _fact(actual, "VERIFIED" if branch_present else
                                    "CONFLICT" if index >= 1 and phase != "synced" else "UNKNOWN",
                                    "present locally" if branch_present else "not present locally"),
        "Branch origin": _fact(origin, "RECORDED") if origin in {"CREATED", "REUSED"}
                         else _fact("UNKNOWN", "UNKNOWN", "no provenance in legacy checkpoint"),
    }
    pending = lambda reached: "YES" if index >= reached else "PENDING"
    if record.get("manual_commit_without_patch") and not record.get("archive_sha256"):
        facts["Patch applied"] = _fact("UNKNOWN", "UNKNOWN", "manual commit without a recorded patch application")
    elif record.get("manually_adopted") and record.get("archive_sha256"):
        facts["Patch applied"] = _fact("ADOPTED", "RECORDED", "manual contents were associated with the handoff")
    else:
        facts["Patch applied"] = _fact(pending(3), "RECORDED" if record else "UNKNOWN")
    verified_checkpoint = any(record.get(field) is not None for field in
                              ("verified_fingerprint", "verified_head", "verified_commit"))
    if verified_checkpoint:
        facts["Checks passed"] = _fact("YES", "RECORDED", "saved verification checkpoint; current bytes not rechecked")
    elif index >= 4:
        facts["Checks passed"] = _fact("UNKNOWN", "UNKNOWN", "no saved verification checkpoint")
    else:
        facts["Checks passed"] = _fact("PENDING", "RECORDED" if record else "UNKNOWN")
    commit_sha = record.get("commit_sha")
    if commit_sha:
        commit_present = _commit_present(root, commit_sha)
        facts["Commit"] = _fact(commit_sha[:12], "VERIFIED" if commit_present else "CONFLICT",
                                "local commit exists" if commit_present else "recorded commit is missing locally")
    else:
        facts["Commit"] = _fact("PENDING" if index < 5 else "UNKNOWN", "RECORDED" if record else "UNKNOWN",
                                "no commit SHA in checkpoint")
    pushed_sha = record.get("pushed_sha")
    facts["Push"] = _fact(pushed_sha[:12] if isinstance(pushed_sha, str) else pending(6),
                          "RECORDED" if pushed_sha or record else "UNKNOWN", "remote not queried")
    number = record.get("pr_number")
    facts["Pull request"] = _fact(f"#{number}" if isinstance(number, int) else "UNKNOWN",
                                  "RECORDED" if isinstance(number, int) else "UNKNOWN", "GitHub not queried")
    facts["Merged"] = _fact(pending(8), "RECORDED" if record else "UNKNOWN", "GitHub not queried")
    facts["Local base synchronized"] = _fact(pending(9), "RECORDED" if record else "UNKNOWN")
    conflict = any(fact.evidence == "CONFLICT" for fact in facts.values())
    if phase in {WorkflowPhase.APPLYING, WorkflowPhase.PATCH_APPLIED,
                 WorkflowPhase.VERIFIED} and record.get("before_patch_head"):
        if current == actual and current_head != record["before_patch_head"]:
            facts["Working HEAD"] = _fact(current_head[:12], "CONFLICT", "changed since patch application")
            conflict = True
    stale_verification = False
    current_fingerprint = None
    current_paths = None
    if (phase == WorkflowPhase.VERIFIED and mode in {"loose", "force"}
            and isinstance(record.get("verified_fingerprint"), str)):
        try:
            current_fingerprint, current_paths = worktree_fingerprint(root)
        except (Abort, OSError):
            facts["Current verification"] = _fact(
                "UNKNOWN", "UNKNOWN", "current working-tree bytes could not be inspected")
            conflict = True
        else:
            stale_verification = (
                current_fingerprint != record["verified_fingerprint"]
                or (record.get("verified_head") is not None
                    and record["verified_head"] != current_head))
            if stale_verification:
                facts["Current verification"] = _fact(
                    "STALE", "VERIFIED", "current bytes or HEAD differ from the saved CHK evidence")
    missing_review = False
    if config.review_required and phase == WorkflowPhase.VERIFIED and not conflict:
        from .commit_scope import policy_fingerprint
        if current_fingerprint is None:
            current_fingerprint, current_paths = worktree_fingerprint(root)
        snapshot = [current, current_head, current_fingerprint,
                    "\x00".join(sorted(current_paths)), policy_fingerprint(root, config)]
        report = record.get("code_review")
        missing_review = not (isinstance(report, dict) and report.get("verdict") == "PASS"
                              and report.get("snapshot") == snapshot)
        facts["Code review"] = _fact("REQUIRED" if missing_review else "PASS",
                                     "RECORDED" if missing_review else "VERIFIED")
    next_action, alternate, guidance = recommend_next_action(
        phase, mode, current, planned_branch, conflict=conflict, dirty=dirty, base=config.base,
        zip_pending_branch=(record.get("zip_first") is True
                            and record.get("applied_branch") == config.base),
        zip_selected=zip_selected, applied_branch=actual,
        require_patch_feature_branch=config.require_patch_feature_branch,
        stale_verification=stale_verification, missing_review=missing_review)
    return PatchStatus(patch, planned_branch, phase, current, facts, next_action, alternate, guidance)


def display_recommendation(status: PatchStatus):
    if status.next_action is None:
        print("==> Next suggested: NONE — " + status.guidance)
    else:
        code, label = ACTION_NAMES[status.next_action]
        print(f"==> {next_action_label(status.next_action, code)} — {label}")
        print("    " + status.guidance)
    if status.alternate_action is not None:
        code, label = ACTION_NAMES[status.alternate_action]
        print(f"Alternative: {status.alternate_action} [{code}] — {label}")


def display_status(status: PatchStatus):
    print("\n==> PATCH STATUS 10 [STS]")
    print(f"Patch: {status.patch}")
    print(f"Planned branch: {status.planned_branch}")
    print(f"Recorded phase: {status.phase}")
    for name, fact in status.facts.items():
        suffix = f" — {fact.detail}" if fact.detail else ""
        print(f"{name}: {fact.value} [{fact.evidence}]{suffix}")
    display_recommendation(status)
