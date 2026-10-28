"""Named local workflow macros built on the guarded feature-session planner."""

from dataclasses import dataclass
from pathlib import Path

from .cli_inspection import show_status_with_progress
from .cli_request import CliRequest, MACRO_OPERATIONS
from .handoff_selection import HandoffSelection, SelectionKind, resolve_handoffs
from .model import Abort, Config
from .planner import build_plan, execute_goal
from .progress import ProgressRecorder


MACRO_NAMES = MACRO_OPERATIONS
LOCAL_MACRO_GOALS = {"APPLY_PATCH": "APPLIED", "APPLY_PATCH_CHECK": "CHECKED"}
LOCAL_MACRO_STEPS = ("APL", "BRN", "CHK")


@dataclass(frozen=True)
class MacroPlan:
    """Immutable initial evidence and planned atomic actions for a named macro."""

    name: str
    goal: str
    patch: str
    scenario: str
    steps: tuple[str, ...]
    verified_satisfied: tuple[str, ...]
    blockers: tuple[str, ...]
    evidence: tuple[str, ...]


def _plan_macro(root: Path, config: Config, selection: HandoffSelection,
                name: str) -> MacroPlan:
    goal = LOCAL_MACRO_GOALS[name]
    plan = build_plan(root, config, selection, goal)
    applicable = LOCAL_MACRO_STEPS[:2 if goal == "APPLIED" else 3]
    satisfied = ()
    if not plan.blockers and plan.scenario in {
            "ALREADY_APPLIED_ZIP", "COMMITTED", "PUBLISHED_CONTINUATION"}:
        satisfied = tuple(step for step in applicable if step not in plan.steps)
    return MacroPlan(name, goal, plan.patch, plan.scenario, plan.steps,
                     satisfied, plan.blockers, plan.evidence)


def _summary(name: str, plan: MacroPlan | None, executed: list[str],
             error: BaseException | None) -> None:
    """Report observed work separately from the original terminal outcome."""
    planned = plan.steps if plan is not None else ()
    unexecuted = tuple(step for step in planned if step not in executed)
    print(f"==> MACRO {name}: {'SUCCESS' if error is None else 'STOPPED'}")
    print(f"    Executed: {', '.join(executed) or 'none'}")
    satisfied = ", ".join(plan.verified_satisfied) if plan is not None else ""
    print(f"    Verified satisfied: {satisfied or 'none'}")
    print(f"    Not executed: {', '.join(unexecuted) or 'none'}")
    if error is not None:
        print("    Recovery: inspect the final STS report and reselect the exact ZIP "
              "before retrying; no automatic rollback was attempted")


def execute_macro(request: CliRequest, root: Path, config: Config,
                  tool_dir: Path) -> None:
    """Execute a guarded local macro and attempt a final STS on every outcome."""
    name = request.op
    if name not in MACRO_NAMES:
        raise Abort("Unsupported macro")
    plan = None
    selected = None
    executed: list[str] = []
    original_error: BaseException | None = None
    try:
        if request.mode != "loose":
            raise Abort(f"MACRO_MODE_UNSUPPORTED: {name} requires LOOSE mode; "
                        "use atomic op/opSeq in STRICT or FORCE")
        if name not in LOCAL_MACRO_GOALS:
            raise Abort(f"MACRO_NOT_IMPLEMENTED: {name} requires WM-05; "
                        "use explicit goal=MERGED for guarded remote publication")
        selected = resolve_handoffs(request, config, root)
        if (selected.handoff is None or selected.handoff.patch_sha256 is None
                or selected.kind == SelectionKind.LEGACY_JSON):
            raise Abort("MACRO_ZIP_REQUIRED: Select an exact self-contained ZIP")
        if selected.handoff.repository != root.name:
            raise Abort("MACRO_REPOSITORY_MISMATCH: The selected ZIP belongs to another project")
        plan = _plan_macro(root, config, selected, name)
        headline = (", ".join(plan.steps) if plan.steps else
                    "BLOCKED" if plan.blockers else "ALREADY_SATISFIED")
        print(f"==> MACRO PLAN {name}: {headline} "
              f"| context={plan.scenario} | ZIP={plan.patch}")
        for detail in plan.evidence:
            print(f"    Evidence: {detail}")
        if plan.blockers:
            raise Abort("MACRO_BLOCKED: " + plan.blockers[0])
        execute_goal(root, config, tool_dir, selected, goal=plan.goal,
                     intent="auto", plan_only=False,
                     skip_approves=request.skip_approves,
                     step_completed=executed.append,
                     macro_check_policy=name == "APPLY_PATCH_CHECK")
    except BaseException as exc:
        original_error = exc
        raise
    finally:
        _summary(name, plan, executed, original_error)
        print(f"==> MACRO {name}: final 10 [STS] (read-only repository inspection)")
        recorder = ProgressRecorder(root)
        try:
            show_status_with_progress(root, config, None,
                                      selected.handoff if selected is not None else None,
                                      None, request.mode, recorder, tool_dir,
                                      zip_selected=selected.zip_selected
                                      if selected is not None else False)
        except (Exception, KeyboardInterrupt) as exc:
            print(f"WARNING: MACRO_FINAL_STS_UNAVAILABLE ({type(exc).__name__}): "
                  "the original macro outcome is unchanged")

