"""Typed lifecycle and operation outcomes shared by all execution modes."""

from enum import Enum


class WorkflowPhase(str, Enum):
    NEW = "new"
    BRANCH_CREATED = "branch_created"
    APPLYING = "applying"
    PATCH_APPLIED = "patch_applied"
    VERIFIED = "verified"
    COMMITTED = "committed"
    PUSHED = "pushed"
    PR_CREATED = "pr_created"
    MERGED = "merged"
    SYNCED = "synced"


class OperationOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    NO_OP = "NO_OP"
    ALREADY_SATISFIED = "ALREADY_SATISFIED"
    UNKNOWN_REMOTE_RESULT = "UNKNOWN_REMOTE_RESULT"


PHASE_VALUES = frozenset(phase.value for phase in WorkflowPhase)
