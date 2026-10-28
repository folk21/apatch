"""Unit tests for the non-fail-fast timeout summary emitted after a test suite."""

from io import StringIO
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._support import run_bounded
from tests.timeout_runner import (IsolatedResult, TimeoutSummaryRunner, is_timeout_error,
                                  run_isolated_test_ids)


class IsolatedSampleCases(unittest.TestCase):
    """Explicitly selected cases are not included in normal test discovery."""

    def case_success(self):
        self.assertTrue(True)

    def case_stall(self):
        time.sleep(20)

    def case_gh_offline(self):
        result = subprocess.run(["gh", "auth", "status"],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 97)
        self.assertIn("TEST_GITHUB_NETWORK_FORBIDDEN", result.stderr)


class TimeoutReportingTests(unittest.TestCase):
    def test_concurrent_timeout_recovers_on_one_serial_retry(self):
        test_id = "tests.sample.RetryableCase.test_work"
        output = StringIO()
        attempts = iter((IsolatedResult(test_id, "TIMEOUT", 0.2, "", ""),
                         IsolatedResult(test_id, "OK", 0.1, "", "")))
        with patch("tests.timeout_runner._run_test_in_process",
                   side_effect=lambda *_: next(attempts)) as run:
            results = run_isolated_test_ids([test_id], timeout_seconds=0.2,
                                            workers=1, stream=output)
        self.assertEqual(run.call_count, 2)
        self.assertEqual([item.outcome for item in results], ["OK"])
        self.assertIn("RETRY OK", output.getvalue())
        self.assertIn("TIMEOUT-AFFECTED TESTS: 1", output.getvalue())
        self.assertIn("recovered on serial retry", output.getvalue())
        self.assertIn("\nOK\n", output.getvalue())

    def test_persistent_timeout_stays_failed_after_one_serial_retry(self):
        test_id = "tests.sample.StalledCase.test_work"
        output = StringIO()
        with patch("tests.timeout_runner._run_test_in_process",
                   return_value=IsolatedResult(test_id, "TIMEOUT", 0.2, "", "")) as run:
            results = run_isolated_test_ids([test_id], timeout_seconds=0.2,
                                            workers=1, stream=output)
        self.assertEqual(run.call_count, 2)
        self.assertEqual([item.outcome for item in results], ["TIMEOUT"])
        self.assertIn("TIMEOUT-AFFECTED TESTS: 1", output.getvalue())
        self.assertIn("not recovered", output.getvalue())
        self.assertIn("FAILED", output.getvalue())

    def test_isolated_runner_times_out_one_test_and_continues(self):
        prefix = f"{__name__}.IsolatedSampleCases"
        output = StringIO()
        results = run_isolated_test_ids(
            [f"{prefix}.case_stall", f"{prefix}.case_success"],
            timeout_seconds=2, workers=2, stream=output)
        outcomes = {result.test_id: result.outcome for result in results}
        self.assertEqual(outcomes[f"{prefix}.case_stall"], "TIMEOUT")
        self.assertEqual(outcomes[f"{prefix}.case_success"], "OK")
        self.assertIn("TIMEOUT-AFFECTED TESTS: 1", output.getvalue())
        self.assertIn(f"{prefix}.case_stall", output.getvalue())

    @unittest.skipUnless(os.name == "posix", "The offline gh guard uses a POSIX stub")
    def test_isolated_runner_blocks_unmocked_gh_commands(self):
        prefix = f"{__name__}.IsolatedSampleCases"
        result = run_isolated_test_ids([f"{prefix}.case_gh_offline"],
                                       timeout_seconds=5, workers=1,
                                       stream=StringIO())
        self.assertEqual(result[0].outcome, "OK")

    def test_bounded_fixture_command_preserves_output_and_failure_status(self):
        cwd = Path(__file__).resolve().parent
        completed = run_bounded([sys.executable, "-c", "print('fixture-ok')"], cwd=cwd)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "fixture-ok")
        failed = run_bounded([sys.executable, "-c", "raise SystemExit(7)"], cwd=cwd)
        self.assertEqual(failed.returncode, 7)
        with self.assertRaises(subprocess.CalledProcessError):
            run_bounded([sys.executable, "-c", "raise SystemExit(7)"],
                        cwd=cwd, check=True)

    def test_bounded_fixture_command_stops_child_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = ("import subprocess,sys,time; "
                      "subprocess.Popen([sys.executable,'-c',"
                      "'import time; time.sleep(20)']); time.sleep(20)")
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                run_bounded([sys.executable, "-c", script],
                            cwd=Path(temporary), timeout_seconds=0.2)
            self.assertEqual(caught.exception.timeout, 0.2)
            self.assertLess(time.monotonic() - started, 3)

    def test_timeout_classification_uses_error_not_test_name(self):
        self.assertTrue(is_timeout_error((RuntimeError, RuntimeError("GitHub timeout"), None)))
        self.assertTrue(is_timeout_error((TimeoutError, TimeoutError(), None)))
        self.assertTrue(is_timeout_error((subprocess.TimeoutExpired,
                                          subprocess.TimeoutExpired(["gh"], 30), None)))
        self.assertFalse(is_timeout_error((AssertionError, AssertionError("wrong value"), None)))

    def test_timeout_summary_lists_only_affected_tests_and_continues(self):
        visited = []

        class Sample(unittest.TestCase):
            def test_a_timeout(self):
                raise RuntimeError("Canonical check stalled with no output for 30s")

            def test_b_failure(self):
                self.fail("ordinary assertion")

            def test_c_success(self):
                visited.append("finished")

        output = StringIO()
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Sample)
        result = TimeoutSummaryRunner(stream=output, verbosity=0).run(suite)
        self.assertEqual(visited, ["finished"])
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.failures), 1)
        text = output.getvalue()
        self.assertIn("TIMEOUT-AFFECTED TESTS: 1", text)
        self.assertIn("test_a_timeout", text)
        self.assertNotIn("  " + Sample("test_b_failure").id() + "\n", text)

    def test_clean_run_reports_zero_timeouts(self):
        class Successful(unittest.TestCase):
            def test_ok(self):
                pass

        output = StringIO()
        result = TimeoutSummaryRunner(stream=output, verbosity=0).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Successful))
        self.assertTrue(result.wasSuccessful())
        self.assertIn("TIMEOUT-AFFECTED TESTS: 0", output.getvalue())
