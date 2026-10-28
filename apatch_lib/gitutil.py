"""Subprocess and repository checks. All commands use argv, never shell=True."""

from collections import deque
from contextvars import ContextVar
import hashlib
import json
import logging
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .model import Abort


LOGGER = logging.getLogger("apatch.commands")
_SKIP_APPROVALS = ContextVar("apatch_skip_approvals", default=False)
_CONFIRMATION_DECLINED = ContextVar("apatch_confirmation_declined", default=False)
REDACT_FLAGS = {"--body", "--token", "--password", "--secret", "--api-key", "--authorization"}
FAILURE_TAIL_LINES = 20
FAILURE_TAIL_LINE_CHARS = 500

COMMAND_DESCRIPTIONS = {
    "switch": "Git branch switch completed",
    "checkout": "Git checkout completed",
    "add": "Git staging completed",
    "commit": "Git commit completed",
    "push": "Git push completed",
    "fetch": "Git fetch completed",
    "pull": "Git pull completed",
    "merge": "Git merge completed",
}


def command_description(argv):
    """Describe significant changes without exposing captured command output."""
    if len(argv) >= 2 and argv[0] == "git":
        return COMMAND_DESCRIPTIONS.get(argv[1])
    if len(argv) >= 3 and argv[:2] == ["gh", "pr"] and argv[2] in {"create", "merge"}:
        return f"GitHub pull request {argv[2]} completed"
    return None


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


def _run_captured_with_deadline(argv, cwd, *, input_text, text, timeout):
    """Kill the full command process group when a network command exceeds its deadline."""
    with subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE if input_text is not None else None,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text,
                          start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                if process.poll() is None:
                    process.kill()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                for pipe in (process.stdout, process.stderr):
                    if pipe is not None:
                        pipe.close()
                if process.poll() is None:
                    process.kill()
            raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def run(argv, cwd: Path, *, input_text=None, check=True, text=True, log_commit_message=None,
        stream_output=False, timeout=None, idle_timeout=None):
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
        if stream_output:
            if input_text is not None or not text:
                raise Abort("Streaming commands must use text output without stdin")
            failure_tail = deque(maxlen=FAILURE_TAIL_LINES)
            with subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, errors="replace",
                                  bufsize=1, start_new_session=True) as process:
                last_output = [time.monotonic()]
                expired = []
                stop_monitor = threading.Event()

                def enforce_deadlines():
                    while not stop_monitor.wait(0.1):
                        now = time.monotonic()
                        if timeout is not None and now - start >= timeout:
                            expired.append(("total", timeout))
                        elif idle_timeout is not None and now - last_output[0] >= idle_timeout:
                            expired.append(("idle", idle_timeout))
                        else:
                            continue
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        return

                monitor = None
                if timeout is not None or idle_timeout is not None:
                    monitor = threading.Thread(target=enforce_deadlines, daemon=True)
                    monitor.start()
                try:
                    assert process.stdout is not None
                    for line in process.stdout:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        failure_tail.append(line.rstrip("\r\n")[-FAILURE_TAIL_LINE_CHARS:])
                        last_output[0] = time.monotonic()
                    returncode = process.wait()
                finally:
                    stop_monitor.set()
                    if monitor is not None:
                        monitor.join(timeout=1)
                if expired:
                    reason, limit = expired[0]
                    LOGGER.error("canonical check timeout reason=%s duration_s=%.3f limit_s=%s argv=%s recent_output=%s",
                                 reason, time.monotonic() - start, limit, command,
                                 json.dumps("\n".join(failure_tail), ensure_ascii=False))
                    print(f"[TIMEOUT] {command} ({time.monotonic() - start:.2f}s)",
                          file=sys.stderr, flush=True)
                    if reason == "idle":
                        raise Abort(f"Canonical check stalled with no output for {limit:g}s: {command}")
                    raise Abort(f"Canonical check timed out after {limit:g}s: {command}")
            result = subprocess.CompletedProcess(argv, returncode, "", "")
        else:
            if timeout is None:
                result = subprocess.run(argv, cwd=cwd, text=text, input=input_text,
                                        capture_output=True, check=False)
            else:
                result = _run_captured_with_deadline(argv, cwd, input_text=input_text,
                                                     text=text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        LOGGER.error("command timed out duration_s=%.3f limit_s=%s argv=%s",
                     duration, timeout, command)
        print(f"[TIMEOUT] {command} ({duration:.2f}s)", file=sys.stderr, flush=True)
        raise Abort(f"Command timed out after {timeout:g}s: {command}. "
                    "The remote operation may have completed; check its status before retrying.") from exc
    except OSError as exc:
        LOGGER.error("command launch failed cwd=%s argv=%s error_type=%s", cwd, command, type(exc).__name__)
        raise Abort(f"Cannot execute {argv[0]}: {exc}") from exc
    duration = time.monotonic() - start
    if stream_output:
        if result.returncode:
            LOGGER.error("check command failed exit=%d duration_s=%.3f argv=%s recent_output=%s",
                         result.returncode, duration, command,
                         json.dumps("\n".join(failure_tail), ensure_ascii=False))
    else:
        level = logging.INFO if result.returncode == 0 else logging.WARNING
        LOGGER.log(level, "command finished exit=%d duration_s=%.3f argv=%s stdout_len=%d stderr_len=%d",
                   result.returncode, duration, command, len(result.stdout), len(result.stderr))
    description = ("Project check completed" if stream_output else command_description(argv))
    if description and result.returncode == 0:
        print(f"[OK] {description} ({duration:.2f}s)", flush=True)
    elif description and result.returncode and check:
        print(f"[FAILED] {description} (exit {result.returncode}, {duration:.2f}s)",
              file=sys.stderr, flush=True)
    if check and result.returncode:
        details = "" if stream_output else f"\n{result.stdout}{result.stderr}"
        raise Abort(f"Command failed ({result.returncode}): {command}{details}")
    return result


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
