"""Pure local action applicability shared by the executor menu and status advice."""

from dataclasses import dataclass

from .core.enums import WorkflowPhase


@dataclass(frozen=True)
class ActionFacts:
    """A local snapshot; absence of a reason never waives live safety checks."""

    mode: str
    phase: str
    branch: str
    planned_branch: str
    applied_branch: str
    base: str
    clean: bool
    zip_selected: bool = False
    zip_first: bool = False
    zip_pending_branch: bool = False
    require_patch_feature_branch: bool = False


PENDING_BRANCH_REASON = (
    "apply-first patch changes must be moved to a feature branch with 1 [BRN]"
)
DEPRECATED_BAP_REASON = (
    "2 [BAP] is deprecated for self-contained ZIP workflows; use 3 [APL], then 1 [BRN]"
)


def _require_phase(
    facts: ActionFacts, phases: tuple[str, ...], *,
    required_branch: str | None = None, clean: bool = False,
) -> str | None:
    if facts.phase not in phases:
        return f"requires phase: {', '.join(phases)}"
    if required_branch is not None and facts.branch != required_branch:
        return f"requires current branch: {required_branch}"
    if clean and not facts.clean:
        return "requires a clean working tree"
    return None


def action_unavailable(number: int, facts: ActionFacts) -> str | None:
    """Return a deterministic local blocker, not permission to mutate Git/GitHub."""
    if number not in range(1, 10):
        raise ValueError(f"Not a lifecycle action: {number}")
    if facts.zip_pending_branch and number != 1:
        return PENDING_BRANCH_REASON
    if number == 2 and facts.zip_first:
        return DEPRECATED_BAP_REASON
    if facts.mode != "strict":
        return None

    if number == 1:
        return (None if facts.zip_pending_branch else
                _require_phase(facts, (WorkflowPhase.NEW.value,),
                               required_branch=facts.base, clean=True))
    if number == 2:
        return _require_phase(facts, (WorkflowPhase.NEW.value,),
                              required_branch=facts.base, clean=True)
    if number == 3:
        required_branch = (
            facts.planned_branch if facts.require_patch_feature_branch
            and not (facts.phase == WorkflowPhase.NEW.value
                     and facts.branch == facts.base and facts.zip_selected)
            else None
        )
        reason = _require_phase(
            facts, (WorkflowPhase.NEW.value, WorkflowPhase.BRANCH_CREATED.value),
            required_branch=required_branch, clean=True)
        return reason or ("requires a checked-out branch" if not facts.branch else None)
    if number == 5:
        reason = _require_phase(facts, (WorkflowPhase.VERIFIED.value,))
        if reason:
            return reason
        if facts.applied_branch != facts.planned_branch:
            return (f"patch was applied to {facts.applied_branch}; automated publishing "
                    f"requires {facts.planned_branch}")
        return _require_phase(facts, (WorkflowPhase.VERIFIED.value,),
                              required_branch=facts.planned_branch)
    requirements: dict[int, tuple[tuple[str, ...], str | None]] = {
        4: ((WorkflowPhase.PATCH_APPLIED.value, WorkflowPhase.VERIFIED.value),
            facts.applied_branch),
        6: ((WorkflowPhase.COMMITTED.value,), facts.planned_branch),
        7: ((WorkflowPhase.PUSHED.value,), facts.planned_branch),
        8: ((WorkflowPhase.PR_CREATED.value,), facts.planned_branch),
        9: ((WorkflowPhase.MERGED.value,), None),
    }
    phases, branch = requirements[number]
    return _require_phase(facts, phases, required_branch=branch)
