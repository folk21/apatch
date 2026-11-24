"""Public feature-session, continuation and guarded-commit contracts."""

from .commit_scope import (CommitScope, NeedsVerification, WaitingForUser,
                           assert_scope_unchanged, inspect_commit_scope)
from .context import ContextReport, GuardFinding, Scenario, inspect_context
from .session import (FeatureSession, attach_applied_workflow, close_feature_session,
                      create_feature_session, remote_identity, validate_feature_sessions)
from .session_continuation import (SessionContinuationEvidence,
                                   require_committed_loose_followup,
                                   require_session_continuation)

__all__ = (
    "CommitScope", "NeedsVerification", "WaitingForUser", "assert_scope_unchanged",
    "inspect_commit_scope", "ContextReport", "GuardFinding", "Scenario",
    "inspect_context", "FeatureSession", "attach_applied_workflow",
    "close_feature_session", "create_feature_session", "remote_identity",
    "validate_feature_sessions", "SessionContinuationEvidence",
    "require_committed_loose_followup", "require_session_continuation",
)
