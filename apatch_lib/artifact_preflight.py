"""Compatibility exports for producer preflight; new code uses handoff.api."""

from .mo_handoff_producer.models import PreflightResult
from .mo_handoff_producer.preflight import preflight

__all__ = ("PreflightResult", "preflight")
