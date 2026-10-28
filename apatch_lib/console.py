"""Small terminal-only presentation helpers without mandatory dependencies."""

import os
import sys


def terminal_style(value: str, code: str) -> str:
    """Keep machine-readable output and redirected logs free of ANSI escapes."""
    if (not sys.stdout.isatty() or "NO_COLOR" in os.environ
            or os.environ.get("TERM") in {None, "", "dumb"}):
        return value
    return f"\033[{code}m{value}\033[0m"


def outcome_label(value: str) -> str:
    color = {
        "SUCCESS": "32", "ERROR": "31", "CANCELLED": "33", "NO_OP": "33",
        "ALREADY_SATISFIED": "32", "UNKNOWN_REMOTE_RESULT": "33",
    }.get(value)
    return terminal_style(value, color) if color is not None else value


def next_action_label(number: int, code: str) -> str:
    return terminal_style(f"Next suggested: {number} [{code}]", "1;36")


def check_result_label(value: str, *, stable: bool) -> str:
    """Use terminal-only amber for drift and green for verified stable bytes."""
    return terminal_style(value, "32" if stable else "33")

