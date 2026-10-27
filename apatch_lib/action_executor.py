"""Execute one workflow action and return explicit, validated completion evidence."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from .core.contracts import ActionResult
from .gitutil import confirmation_was_declined
from .model import Abort

if TYPE_CHECKING:
    from .workflow import Workflow


def execute_workflow_action(workflow: "Workflow", number: int,
                            operation: Callable[[], object], reason: str | None,
                            before_phase: str) -> ActionResult:
    """Own preflight and side-effect dispatch; leave rendering to presentation."""
    if reason:
        raise Abort(f"Action unavailable: {reason}")
    if number in {2, 3}:
        workflow.branch_patch.assert_patch_order()
        workflow.branch_patch.block_unattended_duplicate()
    if number == 3 and workflow.loose:
        if getattr(workflow, "_session_continuation_id", None) is None:
            workflow.loose_actions.assert_followup_selection()
        else:
            workflow.loose_actions.assert_session_continuation()
    previous_cycles: tuple[str, ...] = ()
    if number in {2, 3} and not workflow.skip_previous_cycles:
        previous_cycles = workflow.inspect_previous_cycles()
    evidence = operation()
    try:
        result = ActionResult.completed(evidence, declined=confirmation_was_declined())
    except TypeError as exc:
        raise Abort("Action returned an unsupported completion result") from exc
    if (result.outcome.value == "SUCCESS" and number in {2, 3} and previous_cycles
            and before_phase in {"new", "branch_created"}
            and workflow.phase in {"patch_applied", "verified", "committed", "pushed"}
            and workflow.record.get("archive_sha256")):
        workflow.link_successful_previous_cycles(previous_cycles)
    return result
