"""Process runner for Git, GitHub, and canonical checks; never invokes a shell."""

from collections import deque
import hashlib
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..mo_core.api import Abort


LOGGER = logging.getLogger("apatch.commands")
REDACT_FLAGS = {"--body", "--token", "--password", "--secret", "--api-key", "--authorization"}
FAILURE_TAIL_LINES = 20
FAILURE_TAIL_LINE_CHARS = 500
CHECK_SUMMARY_LINES = 4
CHECK_SUMMARY_CHARS = 240
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

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


def _check_failure_summary(lines):
    """Select bounded, useful error lines from the already-captured check tail."""
    cleaned = [ANSI_ESCAPE.sub("", line).strip()[:CHECK_SUMMARY_CHARS]
               for line in lines if line.strip()]
    if not cleaned:
        return ()
    unresolved = [line for line in cleaned if line.startswith("[APATCH_TEST_FAILURE]")]
    if unresolved:
        return tuple(unresolved[:CHECK_SUMMARY_LINES])
    markers = ("fail:", "failed:", "[failed]", "error:", "[error]",
               "assertionerror", "syntaxerror", "traceback", "changed ")
    chosen = [line for line in cleaned if line.lower().startswith(markers)
              or line.lower().endswith((" failed", " error"))]
    return tuple((chosen or cleaned)[-CHECK_SUMMARY_LINES:])


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
        if stream_output:
            summary = _check_failure_summary(failure_tail)
            if summary:
                details = "\n    Relevant check output:\n" + "\n".join(
                    f"      {line}" for line in summary)
        raise Abort(f"Command failed ({result.returncode}): {command}{details}")
    return result


