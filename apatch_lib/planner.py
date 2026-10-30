"""Bounded, evidence-driven goal plans and guarded publication."""

from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Callable

from . import github
from .commit_scope import WaitingForUser
from .context import (Scenario, inspect_context,
                      inspect_guarded_commit_readiness)
from .gitutil import (current_branch, head, output, remote_head,
                      reset_skip_approvals, set_skip_approvals, status_paths)
from .handoff_selection import HandoffSelection, SelectionKind
from .local_ignore import ensure_runtime_ignored
from .logging_setup import LOG_FILENAME, configure
from .model import Abort, Config
from .params_cache import save_cached_handoff
from .patch import inspect
from .progress import ProgressRecorder
from .session import (close_feature_session, record_session_pr,
                      remote_identity)
from .session_continuation import require_session_continuation
from .state import locked_state, read_state_snapshot
from .status import workflow_key
from .workflow import Workflow
from .zip_resume import verify_applied_zip


LOCAL_GOALS = frozenset({"APPLIED", "CHECKED", "COMMITTED"})
REMOTE_GOALS = frozenset({"PUSHED", "PR_CREATED", "MERGED"})
MAX_LOCAL_STEPS = 4
MAX_GOAL_STEPS = 8
PUBLICATION_STEPS = ("PSH", "PR", "MRG", "SYN")
GOAL_FINAL_STEP = {"PUSHED": "PSH", "PR_CREATED": "PR", "MERGED": "SYN"}
PHASE_NEXT_STEP = {
    "committed": "PSH", "pushed": "PR", "pr_created": "MRG",
    "merged": "SYN", "synced": None,
}


@dataclass(frozen=True)
class ExecutionPlan:
    """A single read-only snapshot, never authority to execute later steps."""

    goal: str
    intent: str
    scenario: str
    patch: str
    branch: str
    session_id: str | None
    steps: tuple[str, ...]
    guards: tuple[str, ...]
    blockers: tuple[str, ...]
    evidence: tuple[str, ...]


def _record(root: Path, handoff, state):
    return state["workflows"].get(workflow_key(root, handoff.branch, handoff.patch))


def _existing_session(state, context, handoff, config):
    if context.session_id is None:
        return None
    record = state.get("feature_sessions", {}).get(context.session_id)
    if (not isinstance(record, dict) or record.get("status") != "active"
            or record.get("feature_branch") != handoff.branch
            or record.get("base_branch") != config.base):
        raise Abort("SESSION_MISMATCH: No unique active feature session was verified")
    return record


def _check_new_continuation(root, config, handoff, context, state):
    """Reject ambiguous or overlapping new ZIPs before entering any APL action."""
    session = _existing_session(state, context, handoff, config)
    if session is None or not session["patch_workflow_keys"]:
        raise Abort("SESSION_REQUIRED: New ZIP on a feature branch needs a verified linked session")
    previous = state["workflows"][session["patch_workflow_keys"][-1]]
    if (previous.get("session_id") != session["session_id"]
            or previous.get("applied_branch") != handoff.branch
            or previous.get("phase") not in {"patch_applied", "verified", "committed"}):
        raise Abort("SESSION_DRIFT: The predecessor is not a uniquely verified pending patch")
    if previous.get("phase") in {"patch_applied", "verified"}:
        if (previous.get("before_patch_head") != head(root)
                or previous.get("remote_url") != output(
                    ["git", "remote", "get-url", config.remote], root)):
            raise Abort("SESSION_DRIFT: Pending patch HEAD or remote changed")
    archive = inspect(config, handoff, root)
    overlap = sorted(set(status_paths(root)) &
                     (set(archive.changed) | set(handoff.delete_paths)))
    if overlap:
        raise WaitingForUser(
            "WAITING_FOR_USER: New ZIP overlaps changed paths: "
            + ", ".join(overlap[:8])
            + "; use supervised LOOSE APL with explicit overlap review")


def _build_local_plan(root: Path, config: Config, selection: HandoffSelection,
                      goal: str, intent: str = "auto") -> ExecutionPlan:
    """Plan using current immutable Git, archive, and checkpoint observations."""
    if goal not in LOCAL_GOALS or intent not in {"auto", "new", "continue"}:
        raise Abort("Unsupported local goal or intent")
    handoff = selection.handoff
    if (handoff is None or handoff.patch_sha256 is None
            or selection.kind not in {SelectionKind.NEW_ZIP,
                                     SelectionKind.APPLIED_ZIP,
                                     SelectionKind.CACHED_WORKFLOW}):
        raise Abort("GOAL_ZIP_REQUIRED: Select an exact self-contained ZIP")
    state = read_state_snapshot(config.state_path)
    record = _record(root, handoff, state)
    effective_branch = record.get("reassigned_branch", handoff.branch) if record else handoff.branch
    context = inspect_context(root, config, handoff=handoff)
    guards = ["Exact ZIP digest and repository", "Fresh branch/HEAD/remote evidence",
              "Session-owned commit scope", "Stable canonical checks"]
    blockers = [f"{finding.code}: {finding.detail}"
                for finding in context.findings if finding.evidence == "CONFLICT"]
    steps: list[str] = []
    branch = current_branch(root)
    session_id = context.session_id
    published_continuation = False
    if (context.scenario == Scenario.UNKNOWN_REMOTE
            and session_id is not None
            and selection.kind == SelectionKind.NEW_ZIP
            and branch == handoff.branch):
        if intent == "new":
            blockers.append("INTENT_CONFLICT: Published continuation requires an active session")
        else:
            try:
                require_session_continuation(root, config, handoff, session_id)
            except Abort as exc:
                blockers.append(str(exc))
            else:
                published_continuation = True
                steps.append("APL")
                if goal != "APPLIED":
                    steps.append("CHK")
                if goal == "COMMITTED":
                    steps.append("CMT")
    elif context.scenario in {Scenario.UNKNOWN_REMOTE, Scenario.AMBIGUOUS,
                            Scenario.BLOCKED, Scenario.MANUAL_DRIFT,
                            Scenario.MISSING_CHECKS}:
        if context.scenario == Scenario.MISSING_CHECKS:
            blockers.append(f"CHECK_CONFIG: root={root}; config={root / '.apatch/config.yaml'}; "
                            f"checks={config.checks}")
        if not blockers:
            blockers.append(f"CONTEXT_UNVERIFIED: {context.scenario.value}")
    elif record and record.get("phase") not in {None, "new"}:
        if intent == "new":
            blockers.append("INTENT_CONFLICT: Already applied ZIP cannot start a new session")
        elif context.scenario != Scenario.ALREADY_APPLIED_ZIP:
            blockers.append("ZIP_CHECKPOINT_CONFLICT: Applied ZIP is not independently verified")
        else:
            phase = record.get("phase")
            if phase in {"committed", "pushed", "pr_created", "merged", "synced"}:
                if (goal in {"APPLIED", "COMMITTED"} and branch == effective_branch
                        and head(root) == record.get("commit_sha")
                        and not status_paths(root)):
                    pass
                else:
                    blockers.append("GOAL_ALREADY_PUBLISHED: A committed workflow cannot "
                                    "be rechecked or changed by a local goal")
            elif phase not in {"patch_applied", "verified"}:
                blockers.append("ZIP_CHECKPOINT_CONFLICT: Application is incomplete")
            else:
                pending_branch = (record.get("zip_first") is True
                                  and record.get("applied_branch") == config.base)
                if pending_branch:
                    steps.append("BRN")
                elif branch != effective_branch:
                    blockers.append("FEATURE_BRANCH_DRIFT: Select the intended feature branch")
                if goal == "APPLIED":
                    pass
                elif not pending_branch:
                    if session_id is not None:
                        workflow = Workflow(root, config, handoff, state, loose=True,
                                            skip_previous_cycles=True)
                        readiness = inspect_guarded_commit_readiness(workflow, session_id)
                        if readiness.status in {"WAITING_FOR_USER", "BLOCKED"}:
                            blockers.append(readiness.detail)
                        elif readiness.status == "READY":
                            if goal == "COMMITTED":
                                steps.append("CMT")
                        else:
                            steps.append("CHK")
                    else:
                        guards.append("Verified existing ZIP must be linked to one session before CHK")
                        steps.append("CHK")
                else:
                    steps.append("CHK")
                if goal == "COMMITTED" and (not steps or steps[-1] != "CMT"):
                    steps.append("CMT")
    elif record and record.get("phase") == "new":
        blockers.append("ZIP_CHECKPOINT_CONFLICT: An incomplete old checkpoint already exists")
    elif context.scenario == Scenario.NEW_BASE:
        if intent == "continue":
            blockers.append("INTENT_CONFLICT: Cannot continue on a clean base branch")
        elif session_id is not None:
            blockers.append("SESSION_CONFLICT: An unfinished feature session already "
                            "owns the planned branch")
        elif selection.kind == SelectionKind.CACHED_WORKFLOW:
            blockers.append("GOAL_ZIP_REQUIRED: New application needs an explicit ZIP")
        else:
            steps.extend(("APL", "BRN"))
            if goal != "APPLIED":
                steps.append("CHK")
            if goal == "COMMITTED":
                steps.append("CMT")
    elif context.scenario in {Scenario.ACTIVE_UNCOMMITTED, Scenario.COMMITTED}:
        if intent == "new" or branch != handoff.branch:
            blockers.append("INTENT_CONFLICT: Continuation requires the intended feature branch")
        elif selection.kind == SelectionKind.CACHED_WORKFLOW:
            blockers.append("GOAL_ZIP_REQUIRED: New application needs an explicit ZIP")
        else:
            try:
                _check_new_continuation(root, config, handoff, context, state)
            except Abort as exc:
                blockers.append(str(exc))
            steps.append("APL")
            if goal != "APPLIED":
                steps.append("CHK")
            if goal == "COMMITTED":
                steps.append("CMT")
    else:
        blockers.append(f"CONTEXT_UNVERIFIED: {context.scenario.value}")
    scenario_label = ("PUBLISHED_CONTINUATION" if published_continuation
                      else context.scenario.value)
    return ExecutionPlan(goal, intent, scenario_label, handoff.patch,
                         branch, session_id, tuple(steps), tuple(guards),
                         tuple(blockers),
                         tuple(f"[{item.evidence}] {item.code}: {item.detail}"
                               for item in context.findings[:8]))


def _live_pr(root: Path, config: Config, handoff, record, *, merged: bool):
    """Prove one recorded PR/revision from fresh GitHub listing and details."""
    number = record.get("pr_number")
    sha = record.get("pushed_sha")
    if type(number) is not int or type(sha) is not str:
        raise Abort("PR_EVIDENCE_MISSING: Recorded PR number or pushed revision is absent")
    repo = github.repository(config, root)
    matching = [pr for pr in github.pr_list(config, root, repo, handoff.branch,
                                            include_other_bases=True)
                if pr["number"] == number and pr["baseRefName"] == config.base]
    if len(matching) != 1:
        raise Abort("PR_IDENTITY_DRIFT: No unique matching PR is present on GitHub")
    listed = matching[0]
    expected_state = "MERGED" if merged else "OPEN"
    if listed["state"] != expected_state:
        raise Abort(f"PR_STATE_DRIFT: Expected {expected_state}, got {listed['state']}")
    github.assert_pr_matches_revision(config, handoff, listed, sha, merged=merged)
    details = github.pr_details(config, root, repo, number)
    if details["state"] != expected_state or (merged and not details.get("mergedAt")):
        raise Abort("PR_STATE_DRIFT: GitHub PR details do not prove the recorded state")
    github.assert_pr_matches_revision(config, handoff, details, sha, merged=merged)
    return details


def _assert_published_identity(root: Path, config: Config, handoff, record, state):
    """Fail closed on stale commit, remote identity or session associations."""
    key = workflow_key(root, handoff.branch, handoff.patch)
    branch = record.get("reassigned_branch", handoff.branch)
    session_id = record.get("session_id")
    session = state.get("feature_sessions", {}).get(session_id)
    if (not isinstance(session, dict)
            or session.get("status") not in {"active", "merged"}
            or key not in session.get("patch_workflow_keys", ())
            or session.get("feature_branch") != branch
            or session.get("base_branch") != config.base
            or session.get("remote_name") != config.remote
            or session.get("remote_identity") != remote_identity(output(
                ["git", "remote", "get-url", config.remote], root))):
        raise Abort("PUBLICATION_SESSION_DRIFT: A unique verified session is required")
    if record.get("remote_url") != output(
            ["git", "remote", "get-url", config.remote], root):
        raise Abort("PUBLICATION_REMOTE_DRIFT: Recorded remote URL changed")
    if (record.get("applied_branch") != branch
            or type(record.get("commit_sha")) is not str
            or record["commit_sha"] not in session.get("commit_shas", ())):
        raise Abort("PUBLICATION_COMMIT_DRIFT: No verified session commit matches the ZIP")
    phase = record.get("phase")
    if phase == "synced":
        if (current_branch(root) != config.base
                or head(root) != record.get("local_base_head")):
            raise Abort("PUBLICATION_BASE_DRIFT: Local synchronized base differs from checkpoint")
    elif phase == "merged" and current_branch(root) == config.base:
        if type(record.get("pr_number")) is not int:
            raise Abort("PUBLICATION_MERGE_DRIFT: A partial sync needs the recorded PR identity")
    elif current_branch(root) != branch or head(root) != record["commit_sha"]:
        raise Abort("PUBLICATION_HEAD_DRIFT: Select the recorded feature commit")
    if status_paths(root):
        raise Abort("PUBLICATION_DIRTY_WORKTREE: Finish local edits before remote operations")
    return session_id


def build_plan(root: Path, config: Config, selection: HandoffSelection,
               goal: str, intent: str = "auto") -> ExecutionPlan:
    """Derive local and remote goals from separately verified current facts."""
    if goal in LOCAL_GOALS:
        return _build_local_plan(root, config, selection, goal, intent)
    if goal not in REMOTE_GOALS or intent not in {"auto", "new", "continue"}:
        raise Abort("Unsupported goal or intent")
    handoff = selection.handoff
    if handoff is None or handoff.patch_sha256 is None:
        raise Abort("GOAL_ZIP_REQUIRED: Select an exact self-contained ZIP")
    state = read_state_snapshot(config.state_path)
    record = _record(root, handoff, state)
    effective_handoff = (replace(handoff, branch=record["reassigned_branch"])
                         if record and record.get("reassigned_branch") else handoff)
    phase = record.get("phase") if record else None
    required = PUBLICATION_STEPS[:PUBLICATION_STEPS.index(GOAL_FINAL_STEP[goal]) + 1]
    remote_guards = ("Exact verified feature-session commit and remote",
                     "Fast-forward-only push", "Current PR number, source SHA and base",
                     "Configured GitHub review/CI and mergeability",
                     "No retry of uncertain remote mutation", "Verified base synchronization")
    if phase not in PHASE_NEXT_STEP:
        local = _build_local_plan(root, config, selection, "COMMITTED", intent)
        return ExecutionPlan(goal, intent, local.scenario, local.patch,
                             local.branch, local.session_id,
                             local.steps + required, local.guards + remote_guards,
                             local.blockers, local.evidence)
    blockers = []
    evidence = [f"[RECORDED] workflow phase={phase}"]
    try:
        verify_applied_zip(root, config, handoff, state)
        session_id = _assert_published_identity(root, config, handoff, record, state)
        if intent == "new":
            raise Abort("INTENT_CONFLICT: Existing ZIP cannot start a new session")
        if phase in {"pushed", "pr_created"} and remote_head(
                root, config, effective_handoff.branch) != record.get("pushed_sha"):
            if phase != "pr_created" or goal != "MERGED":
                raise Abort("PUBLICATION_REMOTE_HEAD_DRIFT: Feature branch no longer matches its pushed SHA")
            _live_pr(root, config, effective_handoff, record, merged=True)
        if phase in {"merged", "synced"} or (
                phase == "pr_created" and goal == "PR_CREATED"):
            details = _live_pr(root, config, effective_handoff, record,
                               merged=phase in {"merged", "synced"})
            if phase == "synced" and goal == "MERGED":
                merged_sha = (details.get("mergeCommit") or {}).get("oid")
                session = state["feature_sessions"][session_id]
                terminal = {"kind": "MERGED_PR", "pr_number": details["number"],
                            "merge_sha": merged_sha}
                if (not merged_sha or session["status"] not in {"active", "merged"}
                        or (session["status"] == "merged"
                            and session.get("terminal_evidence") != terminal)):
                    raise Abort("MERGE_SESSION_DRIFT: Terminal session does not match live PR merge")
                if session["status"] == "active":
                    evidence.append("[RECOVERABLE] Verified sync awaits session finalization")
        if phase in {"merged", "synced"} and goal != "MERGED":
            evidence.append("[VERIFIED] Current revision was merged")
        if phase == "synced" and remote_head(root, config, config.base) != head(root):
            raise Abort("PUBLICATION_BASE_DRIFT: Local base is not equal to its remote HEAD")
    except Abort as exc:
        blockers.append(str(exc))
        session_id = record.get("session_id")
    start = PHASE_NEXT_STEP[phase]
    if start is None or start not in required:
        steps = ()
    else:
        steps = required[required.index(start):]
    if (phase == "synced" and goal == "MERGED" and not blockers
            and state["feature_sessions"][session_id]["status"] == "active"):
        steps = ("FIN",)
    return ExecutionPlan(goal, intent, phase.upper(), handoff.patch,
                         current_branch(root), session_id, tuple(steps),
                         remote_guards, tuple(blockers), tuple(evidence))


def show_plan(plan: ExecutionPlan, *, preview: bool):
    """Print bounded diagnostics without terminal escape sequences."""
    print(f"==> CONTEXT: {plan.scenario} | branch={plan.branch} | patch={plan.patch}")
    print(f"    Session: {plan.session_id or 'not linked'} | intent={plan.intent}")
    summary = (", ".join(plan.steps) if plan.steps
               else "BLOCKED" if plan.blockers else "ALREADY_SATISFIED")
    print(f"==> PLAN {plan.goal}: {summary}")
    if plan.evidence:
        print("==> EVIDENCE: " + " | ".join(plan.evidence))
    print("==> GUARDS: " + "; ".join(plan.guards))
    if plan.blockers:
        print("==> RECOVERY: " + " | ".join(plan.blockers[:5]))
        print("    Read-only inspection: apatch.sh op=STS or op=AUD")
    elif preview:
        print("==> PREVIEW: no state, cache, progress, Git refs or source changes")
    elif plan.goal in REMOTE_GOALS:
        print("==> EXECUTION: explicitly requested remote publication may push, "
              "create a PR, merge, and synchronize the local base")
    else:
        print("==> EXECUTION: local operations only; no push, PR or merge")


def _session_after_apply(workflow: Workflow) -> str:
    """Attach only a successfully applied ZIP to one explicit session."""
    candidates = [record for record in workflow.state.get("feature_sessions", {}).values()
                  if record["status"] == "active"
                  and record["repository"] == str(workflow.root.resolve())
                  and record["feature_branch"] == workflow.handoff.branch]
    if len(candidates) > 1:
        raise Abort("SESSION_AMBIGUOUS: Multiple active sessions own the feature branch")
    session_id = (candidates[0]["session_id"] if candidates
                  else workflow.create_session().session_id)
    workflow.attach_session(session_id)
    return session_id


def _unknown_mutation(workflow: Workflow, step: str) -> bool:
    """Recognize a still-unresolved mutation, not an unrelated historical error."""
    return _unknown_recorded_mutation(workflow.state, workflow.key, step)


def _unknown_recorded_mutation(state, key: str, step: str) -> bool:
    number = {"PR": 7, "MRG": 8}.get(step)
    if number is None:
        return False
    attempts = [entry for entry in state.get("operation_runs", ())
                if entry["workflow_key"] == key
                and entry["operation"]["number"] == number]
    return bool(attempts and attempts[-1]["outcome"] in {"INDETERMINATE", "STARTED"})


def _record_verified_pr(workflow: Workflow, *, merged: bool) -> dict:
    details = _live_pr(workflow.root, workflow.config, workflow.handoff,
                       workflow.record, merged=merged)
    session_id = workflow.record.get("session_id")
    if not isinstance(session_id, str):
        raise Abort("PUBLICATION_SESSION_MISSING: Cannot associate PR with a verified session")
    session = workflow.state["feature_sessions"].get(session_id)
    if session is None or session["status"] != "active":
        raise Abort("PUBLICATION_SESSION_CLOSED: Cannot update a terminal session")
    record_session_pr(workflow.state, session_id,
                      number=details["number"], head_sha=details["headRefOid"],
                      status=details["state"])
    workflow.persist()
    return details


def _reconcile_uncertain(workflow: Workflow, step: str) -> bool:
    """After an uncertain write, adopt only exact live proof; never replay it."""
    if not _unknown_mutation(workflow, step):
        return False
    w = workflow
    repo = github.repository(w.config, w.root)
    expected = w.record.get("pushed_sha")
    prs = [pr for pr in github.pr_list(w.config, w.root, repo, w.handoff.branch)
           if pr["headRefOid"] == expected
           and pr["state"] == ("OPEN" if step == "PR" else "MERGED")
           and (step != "MRG" or pr.get("mergedAt"))]
    if step == "MRG":
        prs = [pr for pr in prs if pr["number"] == w.record.get("pr_number")]
    if len(prs) != 1:
        raise Abort(f"UNKNOWN_REMOTE_RESULT: Previous {step} outcome is uncertain; "
                    "inspect the live PR before a new mutation. No retry was attempted")
    details = github.pr_details(w.config, w.root, repo, prs[0]["number"])
    expected_state = "OPEN" if step == "PR" else "MERGED"
    if details["state"] != expected_state or (step == "MRG" and not details.get("mergedAt")):
        raise Abort(f"UNKNOWN_REMOTE_RESULT: {step} is not independently confirmed")
    github.assert_pr_matches_revision(w.config, w.handoff, details, expected,
                                      merged=step == "MRG")
    w.record["pr_number"] = details["number"]
    w.record["phase"] = "pr_created" if step == "PR" else "merged"
    w.persist()
    _record_verified_pr(w, merged=step == "MRG")
    print(f"==> GOAL {step}: remote outcome reconciled read-only; no mutation replay")
    return True


def _complete_merged_session(workflow: Workflow):
    """Close only after exact PR revision and synchronized base are live-verified."""
    w = workflow
    details = _live_pr(w.root, w.config, w.handoff, w.record, merged=True)
    merge_commit = details.get("mergeCommit")
    merge_sha = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    if not merge_sha:
        raise Abort("MERGE_COMMIT_UNKNOWN: GitHub did not supply a verified merge commit SHA")
    if (current_branch(w.root) != w.config.base
            or head(w.root) != w.record.get("local_base_head")
            or remote_head(w.root, w.config, w.config.base) != head(w.root)):
        raise Abort("SYNC_UNVERIFIED: Local base does not match the verified remote base")
    session_id = w.record["session_id"]
    session = w.state["feature_sessions"][session_id]
    if session["status"] == "active":
        record_session_pr(w.state, session_id,
                          number=details["number"], head_sha=details["headRefOid"],
                          status="MERGED")
        close_feature_session(w.state, session_id, status="merged",
                              pr_number=details["number"], merge_sha=merge_sha)
        w.record["merge_commit_sha"] = merge_sha
        w.persist()
    elif (session["status"] != "merged"
          or session.get("terminal_evidence") != {
              "kind": "MERGED_PR", "pr_number": details["number"],
              "merge_sha": merge_sha}):
        raise Abort("MERGE_SESSION_DRIFT: Terminal session evidence is inconsistent")


def _execute_publication_step(workflow: Workflow, step: str) -> None:
    """Reuse the action journal while guarding each remote phase independently."""
    if _reconcile_uncertain(workflow, step):
        return
    workflow._goal_guarded_publication = True
    try:
        outcome = workflow.interactive(step, show_header=False)
    finally:
        workflow._goal_guarded_publication = False
    if outcome != "SUCCESS":
        raise Abort(f"GOAL_STOPPED: {step} returned {outcome}")
    if step in {"PR", "MRG"}:
        _record_verified_pr(workflow, merged=step == "MRG")
    elif step == "SYN":
        _complete_merged_session(workflow)


def execute_goal(root: Path, config: Config, tool_dir: Path,
                 selection: HandoffSelection, *, goal: str, intent: str,
                 plan_only: bool, skip_approves: bool,
                 step_completed: Callable[[str], None] | None = None,
                 macro_check_policy: bool = False) -> None:
    """Replan before every step; never promote recorded facts to live authority."""
    first = build_plan(root, config, selection, goal, intent)
    show_plan(first, preview=plan_only)
    if plan_only:
        return
    if first.blockers:
        raise Abort("GOAL_BLOCKED: " + first.blockers[0])
    if not first.steps:
        print(f"==> GOAL {goal}: ALREADY_SATISFIED (live local evidence)")
        return
    ensure_runtime_ignored(root, config.log_directory, LOG_FILENAME,
                           config.state_path, config.applied_patches_path)
    configure(config.log_directory)
    recorder = ProgressRecorder(root)
    token = set_skip_approvals(skip_approves)
    workflow = None
    try:
        with locked_state(config.state_path) as state:
            workflow = Workflow(root, config, selection.handoff, state, loose=True,
                                zip_selected=selection.zip_selected,
                                skip_previous_cycles=True, progress_recorder=recorder)
            for _ in range(MAX_GOAL_STEPS if goal in REMOTE_GOALS else MAX_LOCAL_STEPS):
                fresh = build_plan(root, config, selection, goal, intent)
                if fresh.blockers:
                    raise Abort("GOAL_BLOCKED: " + fresh.blockers[0])
                if not fresh.steps:
                    print(f"==> GOAL {goal}: SUCCESS; live goal evidence verified")
                    return
                step = fresh.steps[0]
                print(f"==> GOAL STEP: {step}", flush=True)
                if step == "APL":
                    if fresh.scenario in {Scenario.COMMITTED.value,
                                          "PUBLISHED_CONTINUATION"}:
                        if not fresh.session_id:
                            raise Abort("SESSION_REQUIRED: Committed continuation needs a linked session")
                        outcome = workflow.apply_session_zip(fresh.session_id)
                    else:
                        if fresh.scenario == Scenario.ACTIVE_UNCOMMITTED.value:
                            workflow.allow_followup_zip = True
                            workflow._goal_guarded_continuation = True
                        try:
                            outcome = workflow.interactive("APL", show_header=False)
                        finally:
                            workflow._goal_guarded_continuation = False
                    if outcome != "SUCCESS":
                        raise Abort(f"GOAL_STOPPED: APL returned {outcome}")
                    _session_after_apply(workflow)
                    save_cached_handoff(root, workflow.handoff)
                elif step == "BRN":
                    outcome = workflow.interactive("BRN", show_header=False)
                    if outcome != "SUCCESS":
                        raise Abort(f"GOAL_STOPPED: BRN returned {outcome}")
                elif step in {"CHK", "CMT"}:
                    if fresh.session_id is None:
                        session_id = _session_after_apply(workflow)
                    else:
                        session_id = fresh.session_id
                    workflow._goal_guarded_session_id = session_id
                    workflow._macro_check_policy = macro_check_policy and step == "CHK"
                    try:
                        outcome = workflow.interactive(step, show_header=False)
                    finally:
                        workflow._goal_guarded_session_id = None
                        workflow._macro_check_policy = False
                    if outcome != "SUCCESS":
                        raise Abort(f"GOAL_STOPPED: {step} returned {outcome}")
                elif step in PUBLICATION_STEPS:
                    _execute_publication_step(workflow, step)
                elif step == "FIN":
                    _complete_merged_session(workflow)
                else:
                    raise Abort(f"GOAL_UNSUPPORTED_STEP: {step}")
                if step_completed is not None:
                    step_completed(step)
            final = build_plan(root, config, selection, goal, intent)
            if final.blockers:
                raise Abort("GOAL_BLOCKED: " + final.blockers[0])
            if final.steps:
                raise Abort("GOAL_INCOMPLETE: Requested goal did not converge within step limit")
            print(f"==> GOAL {goal}: SUCCESS; live goal evidence verified")
    except Abort:
        phase = workflow.record.get("phase") if workflow is not None else None
        if (workflow is not None and phase in {"patch_applied", "verified"}
                and current_branch(root) == workflow.handoff.branch):
            print("==> RECOVERY: inspect the blocker, then use "
                  "apatch.sh opSeq=CHK,STS for supervised verification; "
                  "do not reapply a verified ZIP")
        else:
            print("==> RECOVERY: inspect apatch.sh op=STS or op=AUD "
                  "before selecting a safe continuation")
        raise
    finally:
        reset_skip_approvals(token)
        recorder.flush(tool_dir)

