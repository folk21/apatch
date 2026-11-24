"""Historical Git and confirmation facade; execution lives in git.commands."""

from contextvars import ContextVar
import hashlib
import logging
import os
from pathlib import Path

from .mo_core.api import Abort
from .mo_git.commands import (
    LOGGER, REDACT_FLAGS, FAILURE_TAIL_LINES, FAILURE_TAIL_LINE_CHARS,
    CHECK_SUMMARY_LINES, CHECK_SUMMARY_CHARS, ANSI_ESCAPE,
    COMMAND_DESCRIPTIONS, command_description, display_command,
    _check_failure_summary, _run_captured_with_deadline, run,
)

_SKIP_APPROVALS = ContextVar("apatch_skip_approvals", default=False)
_CONFIRMATION_DECLINED = ContextVar("apatch_confirmation_declined", default=False)


def output(argv, cwd: Path, *, timeout=None):
    return run(argv, cwd, timeout=timeout).stdout.strip()


def repository_root(cwd: Path, expected_name: str):
    root = Path(output(["git", "rev-parse", "--show-toplevel"], cwd)).resolve()
    if root != cwd.resolve() or root.name != expected_name:
        raise Abort(f"Run from the root of repository {expected_name!r}: {root}")
    return root


def current_branch(root):
    return output(["git", "branch", "--show-current"], root)


def head(root):
    return output(["git", "rev-parse", "HEAD"], root)


def is_clean(root):
    return not run(["git", "status", "--porcelain", "--untracked-files=all"], root).stdout


def require_clean(root):
    if not is_clean(root):
        raise Abort("Working tree is not clean; inspect git status before continuing")


def require_branch(root, branch):
    if current_branch(root) != branch:
        raise Abort(f"Expected checked-out branch {branch!r}, got {current_branch(root)!r}")


def branch_exists(root, branch):
    result = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], root,
                 check=False)
    if result.returncode not in {0, 1}:
        raise Abort(f"Could not check local branch {branch!r}")
    return result.returncode == 0


def remote_head(root, config, branch):
    result = run(["git", "ls-remote", "--heads", config.remote, f"refs/heads/{branch}"],
                 root, timeout=config.github_timeout_seconds)
    lines = result.stdout.splitlines()
    if not lines:
        return None
    if len(lines) != 1:
        raise Abort(f"Ambiguous remote branch lookup: {branch}")
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != f"refs/heads/{branch}" or len(fields[0]) != 40:
        raise Abort(f"Invalid remote branch response: {branch}")
    return fields[0]


def status_paths(root, *, detect_renames=True):
    """List changed paths, optionally unfolding staged renames into both endpoints."""
    args = ["git", "-c", "core.quotePath=false", "status", "--porcelain=v1",
            "--untracked-files=all", "-z"]
    if not detect_renames:
        args.append("--no-renames")
    data = run(args, root, text=False).stdout
    paths = {}
    items = data.split(b"\x00")
    i = 0
    while i < len(items) and items[i]:
        line = items[i]
        name = os.fsdecode(line[3:])
        code = os.fsdecode(line[:2])
        if "R" in code or "C" in code:
            i += 1
        paths[name] = code
        i += 1
    return paths


def worktree_fingerprint(root):
    """Capture changed bytes, executable bits, and staged Git objects and modes."""
    paths = status_paths(root)
    digest = hashlib.sha256()
    if paths:
        index = run(["git", "ls-files", "--stage", "-z", "--", *sorted(paths)],
                    root, text=False).stdout
        digest.update(b"INDEX\x00" + index + b"\x00")
    for name, code in sorted(paths.items()):
        path = root / name
        digest.update(name.encode("utf-8", "surrogateescape") + b"\x00" + code.encode() + b"\x00")
        if path.is_symlink():
            digest.update(b"L" + os.readlink(path).encode("utf-8", "surrogateescape"))
        elif path.is_file():
            executable = bool(path.stat().st_mode & 0o111)
            digest.update(b"F\x01" if executable else b"F\x00")
            with path.open("rb") as stream:
                for part in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(part)
        elif not path.exists():
            digest.update(b"D")
        else:
            raise Abort(f"Unsupported changed path: {name}")
    return digest.hexdigest(), paths


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

# Compatibility exports retained until all internal callers use git.api.
from .mo_git.models import WorktreeEntry
from .mo_git.inspection import worktree_inventory, worktree_change_details

