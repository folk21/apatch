"""Unit tests for the non-fail-fast timeout summary emitted after a test suite."""

from io import StringIO
import subprocess
import unittest

from tests.timeout_runner import TimeoutSummaryRunner, is_timeout_error


class TimeoutReportingTests(unittest.TestCase):
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
