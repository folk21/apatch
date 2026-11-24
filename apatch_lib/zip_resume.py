"""Compatibility exports for the handoff-owned ZIP resume verifier."""

from .mo_handoff.resume.models import (APPLIED_PHASES, UNCOMMITTED_PHASES,
                                    AppliedZipEvidence)
from .mo_handoff.resume.verification import handoff_signature, verify_applied_zip

__all__ = ("APPLIED_PHASES", "UNCOMMITTED_PHASES", "AppliedZipEvidence",
           "handoff_signature", "verify_applied_zip")
