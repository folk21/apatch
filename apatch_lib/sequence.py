"""Run a validated list of existing workflow operations in order."""

from dataclasses import dataclass

from .model import Abort, RemoteOutcomeUnknown
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
        if 0 in actions:
            raise ValueError("opSeq cannot include EXT; use op=EXT separately")
        if sum(action in {2, 3} for action in actions) > 1:
            raise ValueError("opSeq cannot apply multiple ZIPs from one handoff; run a separate invocation for each patch")
        return cls(actions)


def execute_sequence(workflow, sequence: OperationSequence, *, on_completed=None):
    """Run numbered operations in order, allowing explicit read-only status reports."""
    def describe(number):
        return f"{number} [{ACTION_CODES[number]}]"

    print("\n==> SEQUENCE START: " + ", ".join(map(describe, sequence.actions)))
    print("    skipApproves applies to confirmation prompts, not safety checks")
    last_completed = "NONE"
    for index, action in enumerate(sequence.actions, start=1):
        code = ACTION_CODES[action]
        print(f"\n==> SEQUENCE ACTION {describe(action)}", flush=True)
        try:
            result = workflow.interactive(code, show_header=index == 1)
            if result == "SUCCESS" and on_completed is not None:
                on_completed(action)
        except (Abort, KeyboardInterrupt) as exc:
            remaining = ", ".join(map(describe, sequence.actions[index:])) or "NONE"
            outcome = "UNKNOWN_REMOTE_RESULT" if isinstance(exc, RemoteOutcomeUnknown) else "ERROR"
            print(f"==> SEQUENCE STOP: {describe(action)} | last confirmed: {last_completed} | outcome={outcome}")
            print(f"    Remaining (not executed): {remaining}")
            if isinstance(exc, RemoteOutcomeUnknown):
                print("    Recovery: inspect 10 [STS] and live GitHub PR status; do not replay the remote mutation blindly.")
            else:
                print("    Recovery: inspect 10 [STS] and Git state; explicitly resume from the failed step.")
            failure_type = RemoteOutcomeUnknown if isinstance(exc, RemoteOutcomeUnknown) else Abort
            raise failure_type(f"Sequence operation {describe(action)} stopped: {exc}") from exc
        if action == 10 and result == "NO_OP":
            print("==> SEQUENCE REPORT 10 [STS]: DISPLAYED (read-only)")
        elif result == "ALREADY_SATISFIED" and action == 9:
            print("==> SEQUENCE CONTINUE: 9 [SYN] already synchronized and reverified")
        elif result != "SUCCESS":
            remaining = ", ".join(map(describe, sequence.actions[index:])) or "NONE"
            print(f"==> SEQUENCE STOP: {describe(action)} outcome={result}")
            print(f"    Last confirmed: {last_completed}; remaining (not executed): {remaining}")
            raise Abort("Sequence stopped after an unchanged/cancelled action; inspect 10 [STS] before resuming")
        last_completed = describe(action)
        if index < len(sequence.actions):
            print(f"==> Next scheduled: {describe(sequence.actions[index])}")
    print("\n==> SEQUENCE RESULT: SUCCESS | completed: "
          + ", ".join(map(describe, sequence.actions)))
