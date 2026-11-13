"""Explicit action-result protocol and normalization of legacy action returns."""

from dataclasses import dataclass

from ..publication.api import RemoteOutcomeUnknown
from .enums import OperationOutcome


@dataclass(frozen=True)
class ActionResult:
    """An action's verified completion, independent of incidental Git changes."""

    outcome: OperationOutcome
    evidence: str | None = None
    confirmed_partial_effect: bool = False

    @classmethod
    def succeeded(cls, evidence: str) -> "ActionResult":
        return cls(OperationOutcome.SUCCESS, evidence)

    @classmethod
    def already_satisfied(cls, evidence: str) -> "ActionResult":
        return cls(OperationOutcome.ALREADY_SATISFIED, evidence)

    @classmethod
    def partial(cls, evidence: str) -> "ActionResult":
        """Describe a verified local effect without claiming action completion."""
        return cls(OperationOutcome.NO_OP, evidence, confirmed_partial_effect=True)

    @classmethod
    def completed(cls, value: object, *, declined: bool) -> "ActionResult":
        """Normalize explicit action returns; never infer success from Git deltas."""
        if declined:
            return cls(OperationOutcome.CANCELLED)
        if isinstance(value, cls):
            return value
        if value is True:
            return cls.succeeded("Action returned verified success")
        if value is False or value is None:
            return cls(OperationOutcome.NO_OP)
        raise TypeError(f"Unsupported action return type: {type(value).__name__}")

    @classmethod
    def failed(cls, error: BaseException, *, declined: bool) -> "ActionResult":
        """Give uncertain remote effects priority over local confirmation state."""
        if isinstance(error, RemoteOutcomeUnknown):
            return cls(OperationOutcome.UNKNOWN_REMOTE_RESULT)
        if declined:
            return cls(OperationOutcome.CANCELLED)
        return cls(OperationOutcome.ERROR)

    @property
    def progress_outcome(self) -> str:
        """Preserve existing progress storage's NO_OP spelling."""
        if self.outcome == OperationOutcome.ALREADY_SATISFIED:
            return OperationOutcome.NO_OP.value
        if self.outcome == OperationOutcome.ERROR:
            return "FAILED"
        return self.outcome.value

