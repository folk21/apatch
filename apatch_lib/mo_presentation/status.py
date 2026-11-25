"""Terminal rendering of read-only workflow evidence."""

from apatch_lib.mo_workflows.status import ACTION_NAMES, PatchStatus
from .console import next_action_label

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
