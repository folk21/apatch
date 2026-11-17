"""Compatibility, process isolation, and diagnostics for the Git command transport."""

import logging
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from apatch_lib import gitutil
from apatch_lib.core.api import Abort
from apatch_lib.git import commands


class GitCommandBoundariesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cwd = Path(self.directory.name)

    def test_legacy_runner_and_diagnostics_share_identity(self):
        self.assertIs(gitutil.run, commands.run)
        self.assertIs(gitutil.display_command, commands.display_command)
        self.assertIs(gitutil.command_description, commands.command_description)
        self.assertIs(gitutil._check_failure_summary, commands._check_failure_summary)
        self.assertIs(gitutil._run_captured_with_deadline, commands._run_captured_with_deadline)

    def test_legacy_output_uses_patchable_runner(self):
        with patch.object(gitutil, 'run', return_value=Mock(stdout='  valid-head\n')) as runner:
            self.assertEqual(gitutil.output(['git', 'rev-parse', 'HEAD'], self.cwd), 'valid-head')
            runner.assert_called_once_with(['git', 'rev-parse', 'HEAD'], self.cwd, timeout=None)

    def test_argv_runner_preserves_cwd_and_stdin_without_shell(self):
        value = "literal ; && $(echo ignored)"
        script = 'import os,sys; print(os.getcwd()); print(sys.stdin.read()); print(sys.argv[1])'
        capture = StringIO()
        with redirect_stdout(capture):
            result = commands.run([sys.executable, '-c', script, value], self.cwd,
                                  input_text='input\n')
        self.assertEqual(result.returncode, 0)
        observed_cwd, *output = result.stdout.splitlines()
        self.assertTrue(os.path.samefile(observed_cwd, self.cwd))
        self.assertEqual(output, ['input', '', value])
        self.assertIn('+', capture.getvalue())
        self.assertNotIn('input\n', capture.getvalue())

    def test_runner_accepts_symlinked_cwd(self):
        alias = self.cwd / 'cwd-alias'
        try:
            alias.symlink_to(self.cwd, target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest('Directory symlinks are unavailable')
        result = commands.run([sys.executable, '-c', 'import os; print(os.getcwd())'],
                              alias)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(os.path.samefile(result.stdout.strip(), alias))

    def test_output_is_not_saved_in_success_log(self):
        command = [sys.executable, '-c', "import os; print(os.getenv('APATCH_TEST_SECRET'))"]
        with patch.dict(os.environ, {'APATCH_TEST_SECRET': 'source-secret-never-log'}):
            with self.assertLogs(commands.LOGGER.name, level=logging.INFO) as events:
                commands.run(command, self.cwd)
        self.assertNotIn('source-secret-never-log', '\n'.join(events.output))
        self.assertIn('command finished exit=0', '\n'.join(events.output))

    def test_secret_flags_are_redacted_in_diagnostics(self):
        command = ['gh', 'pr', 'create', '--token', 'sensitive-token',
                   '--body=sensitive-body', '--title', 'example']
        rendered = commands.display_command(command)
        self.assertNotIn('sensitive-token', rendered)
        self.assertNotIn('sensitive-body', rendered)
        self.assertEqual(rendered.count('[REDACTED]'), 2)

    def test_failed_process_can_be_observed_without_mutation(self):
        command = [sys.executable, '-c', 'raise SystemExit(7)']
        result = commands.run(command, self.cwd, check=False)
        self.assertEqual(result.returncode, 7)
        with self.assertRaisesRegex(Abort, r'Command failed \(7\)'):
            commands.run(command, self.cwd)

    def test_deadline_and_commit_message_guard_are_preserved(self):
        with self.assertRaisesRegex(Abort, 'Commit message logging is allowed'):
            commands.run(['git', 'status'], self.cwd,
                         input_text='message', log_commit_message='message')
        with self.assertRaisesRegex(Abort, 'Command timed out'):
            commands.run([sys.executable, '-c', 'import time; time.sleep(10)'],
                         self.cwd, timeout=0.2)

    def test_stream_output_is_console_only_and_rejects_stdin(self):
        script = "import os; print(os.getenv('APATCH_CHECK_OUTPUT'), flush=True)"
        out = StringIO()
        with patch.dict(os.environ, {'APATCH_CHECK_OUTPUT': 'CHECK OUTPUT'}):
            with self.assertLogs(commands.LOGGER.name, level=logging.INFO) as events:
                with redirect_stdout(out):
                    outcome = commands.run([sys.executable, '-c', script], self.cwd,
                                           stream_output=True, timeout=5)
        self.assertEqual(outcome.returncode, 0)
        self.assertIn('CHECK OUTPUT', out.getvalue())
        self.assertNotIn('CHECK OUTPUT', '\n'.join(events.output))
        with self.assertRaisesRegex(Abort, 'Streaming commands must use text output'):
            commands.run([sys.executable, '-c', script], self.cwd,
                         stream_output=True, input_text='unexpected')

    def test_runner_still_is_not_authorization(self):
        self.assertFalse(hasattr(__import__('apatch_lib.git.api', fromlist=['api']), 'run'))
        token = gitutil.set_skip_approvals(True)
        try:
            self.assertTrue(gitutil.skip_approvals_enabled())
        finally:
            gitutil.reset_skip_approvals(token)
        self.assertFalse(gitutil.skip_approvals_enabled())


if __name__ == '__main__':
    unittest.main()
