"""User approval and declined-action context shared by CLI workflow actions."""

from contextvars import ContextVar

from ..mo_core.api import Abort
from ..mo_git.commands import LOGGER

_SKIP_APPROVALS = ContextVar("apatch_skip_approvals", default=False)
_CONFIRMATION_DECLINED = ContextVar("apatch_confirmation_declined", default=False)


def set_skip_approvals(enabled):
    return _SKIP_APPROVALS.set(enabled)


def reset_skip_approvals(token):
    _SKIP_APPROVALS.reset(token)


def skip_approvals_enabled():
    return _SKIP_APPROVALS.get()


def confirm(question):
    if skip_approvals_enabled():
        print(f"{question} [auto-approved: skipApproves=true]")
        LOGGER.warning("confirmation auto-approved question=%s", question)
        return True
    try:
        approved = input(f"{question} Type YES to continue: ").strip() == "YES"
        if not approved:
            _CONFIRMATION_DECLINED.set(True)
        return approved
    except EOFError as exc:
        _CONFIRMATION_DECLINED.set(True)
        raise Abort("Interactive confirmation required; use skipApproves=true to automate approvals") from exc


def clear_confirmation_declined():
    _CONFIRMATION_DECLINED.set(False)


def confirmation_was_declined():
    return _CONFIRMATION_DECLINED.get()
