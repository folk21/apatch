"""Compatibility entry point for workflow phases and outcomes."""

from ..workflows.api import (OperationOutcome as OperationOutcome,
                             PHASE_VALUES as PHASE_VALUES,
                             WorkflowPhase as WorkflowPhase)

__all__ = ("WorkflowPhase", "OperationOutcome", "PHASE_VALUES")
