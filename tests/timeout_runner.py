"""Run independent tests in bounded processes and report timeout-affected IDs."""

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from tests._process_termination import terminate_test_process


_TIMEOUT_TEXT = re.compile(r"\b(?:timed?\s*out|timeout|stalled with no output)\b", re.IGNORECASE)
TEST_CASE_TIMEOUT_SECONDS = 30
MACOS_TEST_CASE_TIMEOUT_SECONDS = 90
MAX_CONFIGURED_TEST_TIMEOUT_SECONDS = 180
MAX_OUTPUT_CHARACTERS = 8000
MAX_TEST_WORKERS = 4
MAX_SERIAL_RETRIES = 3
MACOS_SERIAL_RETRIES = 8
SLOWEST_TEST_LIMIT = 5
FAILURE_SUMMARY_LIMIT = 8
FAILURE_REASON_LIMIT = 180
RUNNER_HEARTBEAT_SECONDS = 10
_ERROR_LINE = re.compile(r"(?:AssertionError|[A-Za-z_][A-Za-z_0-9.]*Error|[A-Za-z_][A-Za-z_0-9.]*Exception):")
_NESTED_TIMEOUT_ERROR = re.compile(
    r"^subprocess\.TimeoutExpired: Command .+ timed out after \d+(?:\.\d+)? seconds?\s*$",
    re.MULTILINE,
)
_ANSI_SGR = re.compile(r"\x1b\[[0-9;]*m")


def classify_test_process_result(returncode, stderr):
    """Retry only a failed unittest that actually raised a subprocess timeout."""
    if returncode == 0:
        return "OK"
    return "TIMEOUT" if _NESTED_TIMEOUT_ERROR.search(_ANSI_SGR.sub("", stderr)) else "FAILED"


def configured_workers(value=None, *, platform=None):
    """Choose a bounded worker count, reducing contention on macOS."""
    platform = sys.platform if platform is None else platform
    if value is None:
        return 2 if platform == "darwin" else 4
    try:
        count = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("APATCH_TEST_WORKERS must be an integer from 1 to 4") from exc
    if str(count) != str(value) or not 1 <= count <= MAX_TEST_WORKERS:
        raise ValueError("APATCH_TEST_WORKERS must be an integer from 1 to 4")
    return count


def configured_test_timeout(value=None, *, platform=None):
    """Choose a bounded wall-clock deadline for subprocess-heavy test cases."""
    platform = sys.platform if platform is None else platform
    if value is None:
        return (MACOS_TEST_CASE_TIMEOUT_SECONDS if platform == "darwin"
                else TEST_CASE_TIMEOUT_SECONDS)
    if (not isinstance(value, str) or len(value) > 3 or not value.isascii()
            or not value.isdecimal() or value.startswith("0")):
        raise ValueError("APATCH_TEST_TIMEOUT_SECONDS must be an integer from 1 to 180")
    timeout = int(value)
    if not 1 <= timeout <= MAX_CONFIGURED_TEST_TIMEOUT_SECONDS:
        raise ValueError("APATCH_TEST_TIMEOUT_SECONDS must be an integer from 1 to 180")
    return timeout


def configured_serial_retries(*, platform=None):
    """Allow bounded recovery for macOS subprocess contention."""
    platform = sys.platform if platform is None else platform
    return MACOS_SERIAL_RETRIES if platform == "darwin" else MAX_SERIAL_RETRIES


def is_timeout_error(error):
    """Classify an actual failed test outcome without inspecting the test name."""
    if error is None:
        return False
    exception = error[1]
    return isinstance(exception, (TimeoutError, subprocess.TimeoutExpired)) or bool(
        _TIMEOUT_TEXT.search(str(exception)))


class TimeoutSummaryResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.timeout_tests = set()

    def addError(self, test, err):
        super().addError(test, err)
        if is_timeout_error(err):
            self.timeout_tests.add(test.id())

    def addFailure(self, test, err):
        super().addFailure(test, err)
        if is_timeout_error(err):
            self.timeout_tests.add(test.id())

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if is_timeout_error(err):
            self.timeout_tests.add(test.id())


class TimeoutSummaryRunner(unittest.TextTestRunner):
    resultclass = TimeoutSummaryResult

    def run(self, test):
        result = super().run(test)
        sys.stdout.flush()
        self.stream.writeln("\nTIMEOUT-AFFECTED TESTS: " + str(len(result.timeout_tests)))
        for test_id in sorted(result.timeout_tests):
            self.stream.writeln("  " + test_id)
        if result.timeout_tests:
            self.stream.writeln("All other tests were allowed to finish; the run remains failed.")
        return result


@dataclass(frozen=True)
class IsolatedResult:
    test_id: str
    outcome: str
    elapsed: float
    stdout: str
    stderr: str


def _flatten_test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten_test_ids(item)
        else:
            yield item.id()


def _failure_reason(result):
    """Select one bounded diagnostic without echoing the complete test output."""
    if result.outcome == "TIMEOUT":
        return "per-test execution deadline exceeded"
    lines = (result.stderr + "\n" + result.stdout).splitlines()
    for line in reversed(lines):
        match = _ERROR_LINE.search(line)
        if match:
            return line[match.start():].strip()[:FAILURE_REASON_LIMIT]
    return "nonzero test result; inspect the detailed output above"


def _print_final_report(results, elapsed_by_id, original_timeouts, recovered,
                        skipped_retries, retried, max_serial_retries, started, stream):
    """Place unresolved failures last so a bounded CHK tail can still report them."""
    failed = [item for item in results if item.outcome != "OK"]
    print(f"\nRan {len(results)} tests in {time.monotonic() - started:.3f}s\n",
          file=stream)
    print(f"FAILED ({len(failed)} failed or timed-out tests)" if failed else "OK",
          file=stream)
    print(f"\nTIMEOUT-AFFECTED TESTS: {len(original_timeouts)}", file=stream)
    for test_id in sorted(original_timeouts):
        status = ("recovered on serial retry" if test_id in recovered
                  else "not retried (retry cap reached)" if test_id in skipped_retries
                  else "not recovered")
        print(f"  {test_id} ({status})", file=stream)
    print(f"SERIAL RETRIES: {retried} attempted, {len(skipped_retries)} skipped "
          f"(cap={max_serial_retries})",
          file=stream)
    slowest = sorted(results, key=lambda item: (-elapsed_by_id[item.test_id], item.test_id))
    print(f"SLOWEST TESTS: {min(SLOWEST_TEST_LIMIT, len(slowest))}", file=stream)
    for item in slowest[:SLOWEST_TEST_LIMIT]:
        print(f"  {item.test_id}: {elapsed_by_id[item.test_id]:.2f}s "
              f"(final result: {item.outcome})", file=stream)
    print(f"FAILED TESTS: {len(failed)}", file=stream)
    for item in failed[:FAILURE_SUMMARY_LIMIT]:
        print(f"[APATCH_TEST_FAILURE] {item.test_id} ({item.outcome}): "
              f"{_failure_reason(item)}", file=stream)
        print(f"  Rerun: {shlex.quote(sys.executable)} -B -m unittest -v "
              f"{shlex.quote(item.test_id)}", file=stream)
    if len(failed) > FAILURE_SUMMARY_LIMIT:
        print(f"  {len(failed) - FAILURE_SUMMARY_LIMIT} additional failed tests; "
              "see earlier results", file=stream)
    stream.flush()


def _run_test_in_process(test_id, root, env, timeout_seconds):
    """Bound each test independently, including grandchildren on POSIX."""
    command = [sys.executable, "-B", "-m", "unittest", test_id, "-v"]
    started = time.monotonic()
    try:
        with subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              start_new_session=os.name == "posix") as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                terminate_test_process(process)
                try:
                    stdout, stderr = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    stdout, stderr = exc.stdout or "", exc.stderr or ""
                return IsolatedResult(test_id, "TIMEOUT", time.monotonic() - started,
                                      stdout or "", stderr or "")
        outcome = classify_test_process_result(process.returncode, stderr)
        return IsolatedResult(test_id, outcome, time.monotonic() - started,
                              stdout, stderr)
    except OSError as exc:
        return IsolatedResult(test_id, "ERROR", time.monotonic() - started,
                              "", str(exc))


def run_isolated_test_ids(test_ids, *, timeout_seconds=TEST_CASE_TIMEOUT_SECONDS,
                          workers=4, max_serial_retries=MAX_SERIAL_RETRIES,
                          stream=None):
    """Execute in parallel without sharing mutable Git fixtures or live GitHub."""
    if not 1 <= workers <= MAX_TEST_WORKERS:
        raise ValueError("workers must be an integer from 1 to 4")
    if not isinstance(max_serial_retries, int) or max_serial_retries < 0:
        raise ValueError("max_serial_retries must be a nonnegative integer")
    stream = sys.stderr if stream is None else stream
    root = Path(__file__).resolve().parents[1]
    started = time.monotonic()
    results = []
    elapsed_by_id = {}
    total = len(test_ids)
    print(f"TEST RUNNER: {total} cases; workers={workers}; "
          f"per-case timeout={timeout_seconds:g}s; "
          f"serial retry cap={max_serial_retries}", file=stream, flush=True)
    with tempfile.TemporaryDirectory(prefix="apatch-offline-gh-") as directory:
        environment = os.environ.copy()
        if os.name == "posix":
            executable = Path(directory) / "gh"
            executable.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "TEST_GITHUB_NETWORK_FORBIDDEN: mock gh before invoking it" >&2\n'
                'exit 97\n',
                encoding="utf-8",
            )
            executable.chmod(0o700)
            environment["PATH"] = directory + os.pathsep + environment.get("PATH", "")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_run_test_in_process, test_id, root, environment,
                            timeout_seconds): test_id
                for test_id in test_ids
            }
            pending = set(futures)
            while pending:
                completed_now, pending = wait(pending, timeout=RUNNER_HEARTBEAT_SECONDS,
                                              return_when=FIRST_COMPLETED)
                if not completed_now:
                    print(f"[WAIT] {len(results)}/{total} complete; "
                          f"{len(pending)} running or queued", file=stream, flush=True)
                    continue
                for future in completed_now:
                    result = future.result()
                    results.append(result)
                    elapsed_by_id[result.test_id] = result.elapsed
                    print(f"[{len(results)}/{total}] {result.test_id} ... "
                          f"{result.outcome} ({result.elapsed:.2f}s)", file=stream, flush=True)
                    if result.outcome != "OK":
                        details = (result.stdout + "\n" + result.stderr).strip()
                        if len(details) > MAX_OUTPUT_CHARACTERS:
                            details = "... [output truncated]\n" + details[-MAX_OUTPUT_CHARACTERS:]
                        if details:
                            print(details, file=stream, flush=True)
        first_timeouts = {item.test_id for item in results if item.outcome == "TIMEOUT"}
        recovered = set()
        skipped_retries = set()
        retried = 0
        for index, result in enumerate(results):
            if result.outcome != "TIMEOUT":
                continue
            if retried >= max_serial_retries:
                skipped_retries.add(result.test_id)
                print(f"RETRY SKIPPED {result.test_id}: "
                      f"serial retry cap {max_serial_retries} reached",
                      file=stream, flush=True)
                continue
            retried += 1
            print(f"RETRY (serial {retried}/{max_serial_retries}) "
                  f"{result.test_id} after concurrent timeout",
                  file=stream, flush=True)
            retry = _run_test_in_process(result.test_id, root, environment, timeout_seconds)
            results[index] = retry
            elapsed_by_id[result.test_id] += retry.elapsed
            if retry.outcome == "OK":
                recovered.add(result.test_id)
            print(f"{result.test_id} ... RETRY {retry.outcome} ({retry.elapsed:.2f}s)",
                  file=stream, flush=True)
            if retry.outcome != "OK":
                details = (retry.stdout + "\n" + retry.stderr).strip()
                if len(details) > MAX_OUTPUT_CHARACTERS:
                    details = "... [output truncated]\n" + details[-MAX_OUTPUT_CHARACTERS:]
                if details:
                    print(details, file=stream, flush=True)
    _print_final_report(results, elapsed_by_id, first_timeouts, recovered,
                        skipped_retries, retried, max_serial_retries, started, stream)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.full:
        if args.tests:
            parser.error("--full cannot be combined with explicit test names")
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(root / "tests"), pattern="test_*.py", top_level_dir=str(root))
    else:
        if not args.tests:
            parser.error("specify test names or --full")
        suite = unittest.defaultTestLoader.loadTestsFromNames(args.tests)
    test_ids = list(_flatten_test_ids(suite))
    try:
        workers = configured_workers(os.environ.get("APATCH_TEST_WORKERS"))
        timeout_seconds = configured_test_timeout(os.environ.get("APATCH_TEST_TIMEOUT_SECONDS"))
    except ValueError as exc:
        parser.error(str(exc))
    results = run_isolated_test_ids(
        test_ids, workers=workers, timeout_seconds=timeout_seconds,
        max_serial_retries=configured_serial_retries())
    return 0 if all(item.outcome == "OK" for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
