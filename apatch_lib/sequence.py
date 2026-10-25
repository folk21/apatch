"""Run a validated list of existing workflow operations in order."""

from dataclasses import dataclass

from .model import Abort
from .workflow import ACTION_CODES, action_number


MAX_SEQUENCE_STEPS = 20


@dataclass(frozen=True)
class OperationSequence:
    actions: tuple[int, ...]

    @classmethod
    def parse(cls, value: str):
        tokens = value.split(",")
        if not value.strip() or any(not token.strip() for token in tokens):
            raise ValueError("opSeq requires nonempty comma-separated action codes or numbers")
        if len(tokens) > MAX_SEQUENCE_STEPS:
            raise ValueError(f"opSeq supports at most {MAX_SEQUENCE_STEPS} steps")
        try:
            actions = tuple(action_number(token.strip()) for token in tokens)
        except ValueError as exc:
            raise ValueError(f"Invalid opSeq: {exc}") from exc
        if any(action in {0, 10} for action in actions):
            raise ValueError("opSeq cannot include EXT or read-only STS; use op=STS separately")
        if sum(action in {2, 3} for action in actions) > 1:
            raise ValueError("opSeq cannot apply multiple ZIPs from one handoff; run a separate invocation for each patch")
        return cls(actions)


def execute_sequence(workflow, sequence: OperationSequence, *, on_completed=None):
    """Stop at the first failure or action without an observed state transition."""
    total = len(sequence.actions)
    print(f"\n==> SEQUENCE START: {total} step(s) | skipApproves applies to each step")
    last_completed = "NONE"
    for index, action in enumerate(sequence.actions, start=1):
        code = ACTION_CODES[action]
        print(f"\n==> SEQUENCE STEP {index}/{total}: {action} [{code}]", flush=True)
        try:
            result = workflow.interactive(code, show_header=index == 1)
            if result == "SUCCESS" and on_completed is not None:
                on_completed(action)
        except (Abort, KeyboardInterrupt) as exc:
            remaining = ", ".join(ACTION_CODES[item] for item in sequence.actions[index:]) or "NONE"
            print(f"==> SEQUENCE STOP: step {index}/{total} ({action} [{code}]) | last completed: {last_completed}")
            print(f"    Remaining (not executed): {remaining}")
            print("    Recovery: inspect 10 [STS] and Git state; explicitly resume from the failed step.")
            raise Abort(f"Sequence step {index}/{total} ({code}) stopped: {exc}") from exc
        if result != "SUCCESS":
            remaining = ", ".join(ACTION_CODES[item] for item in sequence.actions[index:]) or "NONE"
            print(f"==> SEQUENCE STOP: step {index}/{total} ({action} [{code}]) outcome={result}")
            print(f"    Last completed: {last_completed}; remaining (not executed): {remaining}")
            raise Abort("Sequence stopped after an unchanged/cancelled action; inspect 10 [STS] before resuming")
        last_completed = f"{index}/{total} ({action} [{code}])"
        if index < total:
            next_action = sequence.actions[index]
            print(f"==> Next scheduled: {next_action} [{ACTION_CODES[next_action]}] ({index + 1}/{total})")
    print(f"\n==> SEQUENCE RESULT: SUCCESS ({total}/{total} steps)")
