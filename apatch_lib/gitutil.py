"""Subprocess and repository checks. All commands use argv, never shell=True."""

import hashlib
import json
import logging
import os
import shlex
import subprocess
import time
from pathlib import Path

from .model import Abort


LOGGER = logging.getLogger("apatch.commands")
REDACT_FLAGS = {"--body", "--token", "--password", "--secret", "--api-key", "--authorization"}


def display_command(argv):
    """Keep the command auditable without persisting common secret-bearing values."""
    visible = []
    hide_next = False
    for item in argv:
        value = os.fspath(item)
        if hide_next:
            visible.append("[REDACTED]")
            hide_next = False
        elif value in REDACT_FLAGS:
            visible.append(value)
            hide_next = True
        elif any(value.startswith(flag + "=") for flag in REDACT_FLAGS):
            visible.append(value.split("=", 1)[0] + "=[REDACTED]")
        else:
            visible.append(value)
    return shlex.join(visible).replace("\n", "\\n").replace("\r", "\\r")


def run(argv, cwd: Path, *, input_text=None, check=True, text=True, log_commit_message=None):
    command = display_command(argv)
    print("+", command, flush=True)
    if log_commit_message is not None:
        if list(argv)[:2] != ["git", "commit"] or input_text != log_commit_message:
            raise Abort("Commit message logging is allowed only for its matching git commit")
        LOGGER.info("command start cwd=%s argv=%s commit_message=%s",
                    cwd, command, json.dumps(log_commit_message, ensure_ascii=False))
    else:
        LOGGER.info("command start cwd=%s argv=%s", cwd, command)
    start = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=cwd, text=text, input=input_text,
                                capture_output=True, check=False)
    except OSError as exc:
        LOGGER.error("command launch failed cwd=%s argv=%s error_type=%s", cwd, command, type(exc).__name__)
        raise Abort(f"Cannot execute {argv[0]}: {exc}") from exc
    duration = time.monotonic() - start
    level = logging.INFO if result.returncode == 0 else logging.WARNING
    LOGGER.log(level, "command finished exit=%d duration_s=%.3f argv=%s stdout_len=%d stderr_len=%d",
               result.returncode, duration, command, len(result.stdout), len(result.stderr))
    if check and result.returncode:
        raise Abort(f"Command failed ({result.returncode}): {command}\n"
                    f"{result.stdout}{result.stderr}")
    return result


def output(argv, cwd: Path):
    return run(argv, cwd).stdout.strip()


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
    result = run(["git", "ls-remote", "--heads", config.remote, f"refs/heads/{branch}"], root)
    lines = result.stdout.splitlines()
    if not lines:
        return None
    if len(lines) != 1:
        raise Abort(f"Ambiguous remote branch lookup: {branch}")
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != f"refs/heads/{branch}" or len(fields[0]) != 40:
        raise Abort(f"Invalid remote branch response: {branch}")
    return fields[0]


def status_paths(root):
    data = run(["git", "-c", "core.quotePath=false", "status", "--porcelain=v1",
                "--untracked-files=all", "-z"], root, text=False).stdout
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
    """Capture all changed/untracked bytes, including symlink targets and deletions."""
    paths = status_paths(root)
    digest = hashlib.sha256()
    for name, code in sorted(paths.items()):
        path = root / name
        digest.update(name.encode("utf-8", "surrogateescape") + b"\x00" + code.encode() + b"\x00")
        if path.is_symlink():
            digest.update(b"L" + os.readlink(path).encode("utf-8", "surrogateescape"))
        elif path.is_file():
            digest.update(b"F")
            with path.open("rb") as stream:
                for part in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(part)
        elif not path.exists():
            digest.update(b"D")
        else:
            raise Abort(f"Unsupported changed path: {name}")
    return digest.hexdigest(), paths


def confirm(question):
    return input(f"{question} Type YES to continue: ").strip() == "YES"
