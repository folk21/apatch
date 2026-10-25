"""Read-only, offline evidence and next-action guidance for a patch cycle."""

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .model import Abort, BRANCH_PATTERN


PHASE_ORDER = ("new", "branch_created", "applying", "patch_applied", "verified",
               "committed", "pushed", "pr_created", "merged", "synced")
ACTION_NAMES = {
    1: ("BRN", "Prepare the feature branch"),
    3: ("APL", "Apply the patch"),
    4: ("CHK", "Run canonical checks"),
    5: ("CMT", "Commit verified changes"),
    6: ("PSH", "Push the recorded commit"),
    7: ("PR", "Create or find the pull request"),
    8: ("MRG", "Merge the pull request after GitHub policy checks"),
    9: ("SYN", "Synchronize the local base branch"),
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
                          *, conflict=False, dirty=False, base="main", zip_pending_branch=False):
    """Provide cautious guidance; this never replaces a command's live guards."""
    if conflict or phase == "applying":
        return None, None, "Inspect or reconcile the conflicting/interrupted workflow before continuing."
    if phase == "synced":
        return None, None, "Workflow completed; no further lifecycle operation is needed."
    if phase == "new":
        if mode == "strict" and branch == planned_branch:
            return 3, None, "Verify live guards before applying."
        if mode == "strict" and (branch != base or dirty):
            return None, None, "STRICT branch creation requires a clean worktree on the base branch."
        return 1, 3 if mode != "strict" else None, "Select the intended branch before applying."
    if phase == "branch_created":
        if mode == "strict" and (branch != planned_branch or dirty):
            return None, None, "STRICT patch application requires the prepared branch and clean worktree."
        return 3, None, "Check the selected ZIP and target branch before applying."
    if phase == "patch_applied":
        if zip_pending_branch:
            return 1, None, "Move the uncommitted ZIP changes from the base branch to the planned feature branch."
        return 4, 3 if mode == "loose" else None, "Verify the current changed bytes before commit."
    if phase == "verified":
        if mode == "strict" and branch != planned_branch:
            return None, None, "STRICT publishing requires the planned feature branch."
        return 5, 3 if mode == "loose" else None, "Check the planned commit scope and message."
    if phase == "committed":
        return 6, None, "Push only after checking the recorded commit and remote branch."
    if phase == "pushed":
        return 7, None, "GitHub PR discovery and creation require network access."
    if phase == "pr_created":
        return 8, None, "Merge requires live GitHub review and CI policy checks."
    if phase == "merged":
        return 9, None, "Confirm remote merge and synchronize the local base branch."
    return None, None, "No reliable next action can be inferred from this checkpoint."


def inspect_patch(root: Path, config, record: dict, patch: str, planned_branch: str, mode: str):
    """Compare stored claims with local facts; never query GitHub or change state."""
    if not isinstance(record, dict):
        raise Abort("Invalid stored workflow record")
    phase = record.get("phase", "new")
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
    if phase in {"applying", "patch_applied", "verified"} and record.get("before_patch_head"):
        if current == actual and current_head != record["before_patch_head"]:
            facts["Working HEAD"] = _fact(current_head[:12], "CONFLICT", "changed since patch application")
            conflict = True
    next_action, alternate, guidance = recommend_next_action(
        phase, mode, current, planned_branch, conflict=conflict, dirty=dirty, base=config.base,
        zip_pending_branch=(record.get("zip_first") is True
                            and record.get("applied_branch") == config.base))
    return PatchStatus(patch, planned_branch, phase, current, facts, next_action, alternate, guidance)


def display_recommendation(status: PatchStatus):
    if status.next_action is None:
        print("Next suggested: NONE — " + status.guidance)
    else:
        code, label = ACTION_NAMES[status.next_action]
        print(f"Next suggested: {status.next_action} [{code}] — {label}")
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
