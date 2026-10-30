"""Run a validated list of existing workflow operations in order."""

from dataclasses import dataclass
import uuid

from .model import Abort, CheckWorktreeChanged, RemoteOutcomeUnknown
from .core.actions import ACTION_CODES, action_number


MAX_SEQUENCE_STEPS = 20


@dataclass(frozen=True)
class OperationSequence:
    actions: tuple[int, ...]

    @classmethod
    def parse(cls, value: str, *, allow_multiple_apl=False):
        tokens = value.split(",")
        if not value.strip() or any(not token.strip() for token in tokens):
            raise ValueError("opSeq requires nonempty comma-separated action codes or numbers")
        if len(tokens) > MAX_SEQUENCE_STEPS:
            raise ValueError(f"opSeq supports at most {MAX_SEQUENCE_STEPS} steps")
        try:
            actions = tuple(action_number(token.strip()) for token in tokens)
        except ValueError as exc:
            raise ValueError(f"Invalid opSeq: {exc}") from exc
        if 0 in actions:
            raise ValueError("opSeq cannot include EXT; use op=EXT separately")
        if sum(action in {2, 3} for action in actions) > 1 and not allow_multiple_apl:
            raise ValueError("opSeq cannot apply multiple ZIPs from one handoff; run a separate invocation for each patch")
        if allow_multiple_apl and 2 in actions and sum(action in {2, 3} for action in actions) > 1:
            raise ValueError("Multi-handoff opSeq supports APL, not deprecated BAP")
        return cls(actions)


def parse_handoff_sequence(value: str):
    """Parse an explicit one-to-one list of ZIP selections for APL actions."""
    names = tuple(token.strip() for token in value.split(","))
    if not names or any(not name for name in names):
        raise ValueError("handoffSeq requires nonempty comma-separated ZIP selections")
    if len(names) > MAX_SEQUENCE_STEPS:
        raise ValueError(f"handoffSeq supports at most {MAX_SEQUENCE_STEPS} ZIPs")
    return names


def validate_multi_handoff_actions(sequence: OperationSequence, selections: tuple[str, ...], mode: str):
    """Reject sequences that could apply multiple ZIPs on the base or publish too early."""
    actions = sequence.actions
    apply_indices = [index for index, action in enumerate(actions) if action == 3]
    if not apply_indices or len(apply_indices) != len(selections):
        raise ValueError("handoffSeq must select exactly one distinct ZIP for each APL operation")
    if len(selections) == 1:
        return
    if mode != "loose":
        raise ValueError("Multiple ZIPs in one opSeq require LOOSE mode; STRICT/FORCE cannot accumulate them")
    if actions[:2] != (3, 1):
        raise ValueError("Multi-ZIP sequences must begin with APL,BRN before another APL")
    if 1 in actions[2:]:
        raise ValueError("Multi-ZIP sequences must transfer to the feature branch exactly once")
    if any(action in {5, 6, 7, 8, 9} for action in actions[:apply_indices[-1]]):
        raise ValueError("Apply all ZIPs before commit/push/PR/merge/sync in a multi-ZIP sequence")


def execute_sequence(workflow, sequence: OperationSequence, *, on_completed=None,
                     select_workflow=None, on_satisfied=None):
    """Run numbered operations in order, allowing explicit read-only status reports."""
    def describe(number):
        return f"{number} [{ACTION_CODES[number]}]"

    print("\n==> SEQUENCE START: " + ", ".join(map(describe, sequence.actions)))
    print("    skipApproves applies to confirmation prompts, not safety checks")
    if (sequence.actions and getattr(workflow, "phase", None) == "synced"
            and sequence.actions[0] == 4
            and any(action in {5, 6, 7, 8, 9} for action in sequence.actions[1:])):
        from .gitutil import current_branch, is_clean
        if (current_branch(workflow.root) == workflow.config.base
                and is_clean(workflow.root)):
            print("==> SEQUENCE ALREADY COMPLETED: The selected ZIP is merged and "
                  "the clean base branch is synchronized.")
            print("    No canonical checks, commit, push, PR, or merge were attempted.")
            print("    Run op=STS to inspect the completed ZIP, or select a new ZIP with APL.")
            return "ALREADY_COMPLETED"
    last_completed = "NONE"
    sequence_id = uuid.uuid4().hex
    executed: list[str] = []
    satisfied: list[str] = []
    reported: list[str] = []
    for index, action in enumerate(sequence.actions, start=1):
        code = ACTION_CODES[action]
        print(f"\n==> SEQUENCE ACTION {describe(action)}", flush=True)
        replay_free = False
        try:
            if select_workflow is not None and action == 3:
                workflow = select_workflow(index, workflow)
                print(f"    Selected ZIP: {workflow.handoff.patch}", flush=True)
            workflow.progress_sequence = (sequence_id, index, len(sequence.actions))
            result = on_satisfied(action, workflow) if on_satisfied is not None else None
            if result == "ALREADY_SATISFIED":
                replay_free = True
            elif result is None:
                result = workflow.interactive(code, show_header=index == 1)
            if result == "SUCCESS" and on_completed is not None:
                on_completed(action, workflow)
        except (Abort, KeyboardInterrupt) as exc:
            remaining = ", ".join(map(describe, sequence.actions[index:])) or "NONE"
            outcome = "UNKNOWN_REMOTE_RESULT" if isinstance(exc, RemoteOutcomeUnknown) else "ERROR"
            print(f"==> SEQUENCE STOP: {describe(action)} | last confirmed: {last_completed} | outcome={outcome}")
            print(f"    Remaining (not executed): {remaining}")
            if isinstance(exc, CheckWorktreeChanged):
                print("    Recovery: check-produced edits were preserved; review them and resume "
                      "with opSeq=CHK,STS. No ZIP replay is needed.")
            elif isinstance(exc, RemoteOutcomeUnknown):
                print("    Recovery: inspect 10 [STS] and live GitHub PR status; do not replay the remote mutation blindly.")
            else:
                print("    Recovery: inspect 10 [STS] and Git state; explicitly resume from the failed step.")
            failure_type = RemoteOutcomeUnknown if isinstance(exc, RemoteOutcomeUnknown) else Abort
            raise failure_type(f"Sequence operation {describe(action)} stopped: {exc}") from exc
        if action == 10 and result == "NO_OP":
            reported.append(describe(action))
            print("==> SEQUENCE REPORT 10 [STS]: DISPLAYED (read-only)")
        elif result == "ALREADY_SATISFIED" and (action == 9 or (replay_free and action in {1, 3})):
            satisfied.append(describe(action))
            if action == 9:
                print(f"==> SEQUENCE CONTINUE: {describe(action)} already synchronized")
            else:
                print(f"==> SEQUENCE CONTINUE: {describe(action)} already satisfied and reverified")
        elif result != "SUCCESS":
            remaining = ", ".join(map(describe, sequence.actions[index:])) or "NONE"
            print(f"==> SEQUENCE STOP: {describe(action)} outcome={result}")
            print(f"    Last confirmed: {last_completed}; remaining (not executed): {remaining}")
            raise Abort("Sequence stopped after an unchanged/cancelled action; inspect 10 [STS] before resuming")
        else:
            executed.append(describe(action))
        last_completed = describe(action)
        if index < len(sequence.actions):
            print(f"==> Next scheduled: {describe(sequence.actions[index])}")
    print("\n==> SEQUENCE RESULT: SUCCESS | completed: "
          + ", ".join(map(describe, sequence.actions)))
    print("    Executed: " + (", ".join(executed) or "NONE"))
    print("    Already satisfied: " + (", ".join(satisfied) or "NONE"))
    print("    Read-only reports: " + (", ".join(reported) or "NONE"))
    print("    Not executed: NONE")
