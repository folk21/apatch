"""Compatibility exports for producer preflight; new code uses handoff.api."""

from .handoff.producer.models import PreflightResult
from .handoff.producer.preflight import preflight

__all__ = ("PreflightResult", "preflight")
