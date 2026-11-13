"""Compatibility entry point for historical domain contract imports.

The owning definitions live in workflows and publication. This shim remains
until callers and the supported external import surface have been reviewed.
"""

from ..publication.api import (GitHubPr as GitHubPr,
                               GitHubPrIdentity as GitHubPrIdentity,
                               RemoteOutcomeUnknown as RemoteOutcomeUnknown)
from ..workflows.api import (ActionResult as ActionResult,
                             StateDocument as StateDocument,
                             WorkflowRecord as WorkflowRecord)

__all__ = ("WorkflowRecord", "StateDocument", "ActionResult",
           "GitHubPr", "GitHubPrIdentity", "RemoteOutcomeUnknown")
