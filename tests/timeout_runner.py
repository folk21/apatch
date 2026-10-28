"""Run the ordinary unittest suites and summarize tests affected by command timeouts."""

import re
import subprocess
import sys
import unittest
from pathlib import Path


_TIMEOUT_TEXT = re.compile(r"\b(?:timed?\s*out|timeout|stalled with no output)\b", re.IGNORECASE)


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


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--full":
        root = Path(__file__).resolve().parents[1]
        suite = unittest.defaultTestLoader.discover(
            start_dir=str(root / "tests"), pattern="test_*.py", top_level_dir=str(root))
        result = TimeoutSummaryRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    unittest.main(module=None, testRunner=TimeoutSummaryRunner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
