"""Bounded, evidence-driven local goals; remote publication remains explicit."""

from dataclasses import dataclass
from pathlib import Path

from .commit_scope import WaitingForUser
from .context import (Scenario, inspect_context,
                      inspect_guarded_commit_readiness)
from .gitutil import (current_branch, head, output, reset_skip_approvals,
                      set_skip_approvals, status_paths)
from .handoff_selection import HandoffSelection, SelectionKind
from .local_ignore import ensure_runtime_ignored
from .logging_setup import LOG_FILENAME, configure
from .model import Abort, Config
from .params_cache import save_cached_handoff
from .patch import inspect
from .progress import ProgressRecorder
from .session import remote_identity
from .state import locked_state, read_state_snapshot
from .status import workflow_key
from .workflow import Workflow
from .zip_resume import verify_applied_zip


LOCAL_GOALS = frozenset({"CHECKED", "COMMITTED"})
MAX_LOCAL_STEPS = 4


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


def build_plan(root: Path, config: Config, selection: HandoffSelection,
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
    context = inspect_context(root, config, handoff=handoff)
    guards = ["Exact ZIP digest and repository", "Fresh branch/HEAD/remote evidence",
              "Session-owned commit scope", "Stable canonical checks"]
    blockers = [f"{finding.code}: {finding.detail}"
                for finding in context.findings if finding.evidence == "CONFLICT"]
    steps: list[str] = []
    branch = current_branch(root)
    session_id = context.session_id
    if context.scenario in {Scenario.UNKNOWN_REMOTE, Scenario.AMBIGUOUS,
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
                if (goal == "COMMITTED" and branch == handoff.branch
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
                elif branch != handoff.branch:
                    blockers.append("FEATURE_BRANCH_DRIFT: Select the intended feature branch")
                if not pending_branch:
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
            steps.extend(("APL", "BRN", "CHK"))
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
            steps.extend(("APL", "CHK"))
            if goal == "COMMITTED":
                steps.append("CMT")
    else:
        blockers.append(f"CONTEXT_UNVERIFIED: {context.scenario.value}")
    return ExecutionPlan(goal, intent, context.scenario.value, handoff.patch,
                         branch, session_id, tuple(steps), tuple(guards),
                         tuple(blockers),
                         tuple(f"[{item.evidence}] {item.code}: {item.detail}"
                               for item in context.findings[:8]))


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


def execute_goal(root: Path, config: Config, tool_dir: Path,
                 selection: HandoffSelection, *, goal: str, intent: str,
                 plan_only: bool, skip_approves: bool) -> None:
    """Replan after every local step; never expand the goal into remote actions."""
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
            for _ in range(MAX_LOCAL_STEPS):
                fresh = build_plan(root, config, selection, goal, intent)
                if fresh.blockers:
                    raise Abort("GOAL_BLOCKED: " + fresh.blockers[0])
                if not fresh.steps:
                    print(f"==> GOAL {goal}: SUCCESS; no remote operations executed")
                    return
                step = fresh.steps[0]
                print(f"==> GOAL STEP: {step}", flush=True)
                if step == "APL":
                    if fresh.scenario == Scenario.COMMITTED.value:
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
                    try:
                        outcome = workflow.interactive(step, show_header=False)
                    finally:
                        workflow._goal_guarded_session_id = None
                    if outcome != "SUCCESS":
                        raise Abort(f"GOAL_STOPPED: {step} returned {outcome}")
                else:
                    raise Abort(f"GOAL_UNSUPPORTED_STEP: {step}")
            final = build_plan(root, config, selection, goal, intent)
            if final.blockers or final.steps:
                raise Abort("GOAL_INCOMPLETE: Local goal did not converge within step limit")
            print(f"==> GOAL {goal}: SUCCESS; no remote operations executed")
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
