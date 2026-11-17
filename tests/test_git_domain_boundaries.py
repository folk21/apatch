"""Contract regression tests for the read-only Git domain API."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from apatch_lib import gitutil
from apatch_lib.core.api import Abort
from apatch_lib.git import api as git_api
from tests._support import LocalGitFixture, command


class GitDomainBoundaryTests(LocalGitFixture):
    def test_historical_imports_are_identity_preserving(self):
        self.assertIs(git_api.WorktreeEntry, gitutil.WorktreeEntry)
        self.assertIs(git_api.worktree_inventory, gitutil.worktree_inventory)
        self.assertIs(git_api.worktree_change_details, gitutil.worktree_change_details)

    def test_models_are_frozen_and_contain_no_runtime_io(self):
        model_file = Path(git_api.WorktreeEntry.__module__.replace('.', '/'))
        file = Path(__file__).resolve().parents[1] / (str(model_file) + '.py')
        source = file.read_text(encoding='utf-8')
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom))
                             and ('subprocess' in ast.unparse(node) or 'gitutil' in ast.unparse(node))
                             for node in tree.body))
        entry = git_api.WorktreeEntry(' M', (), 'file', bytes_sha256='a' * 64)
        with self.assertRaises(FrozenInstanceError):
            entry.status = '??'

    def test_clean_repository_snapshot_is_read_only(self):
        before = command('git', 'status', '--porcelain', cwd=self.root).stdout
        repository = git_api.inspect_repository(self.root)
        inventory = git_api.inspect_worktree(self.root)
        self.assertEqual(repository.root, self.root.resolve())
        self.assertEqual(repository.branch, 'main')
        self.assertEqual(repository.head, self.head)
        self.assertFalse(repository.dirty)
        self.assertEqual(inventory.entries, ())
        self.assertEqual(inventory.changed_paths, ())
        self.assertEqual(command('git', 'status', '--porcelain', cwd=self.root).stdout, before)
        self.assertEqual(command('git', 'rev-parse', 'HEAD', cwd=self.root).stdout.strip(), self.head)

    def test_staged_unstaged_untracked_and_executable_are_observed(self):
        (self.root / 'existing.txt').write_text('modified\n', encoding='utf-8')
        command('git', 'add', 'existing.txt', cwd=self.root)
        (self.root / 'existing.txt').write_text('modified again\n', encoding='utf-8')
        script = self.root / 'tool.sh'
        script.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        script.chmod(0o755)
        before = git_api.worktree_inventory(self.root)
        state = git_api.inspect_worktree(self.root)
        self.assertEqual(dict(state.entries), before)
        self.assertEqual(state.changed_paths, ('existing.txt', 'tool.sh'))
        self.assertEqual(dict(state.entries)['tool.sh'].kind, 'file')
        self.assertTrue(dict(state.entries)['tool.sh'].executable)
        self.assertTrue(dict(state.entries)['existing.txt'].index)
        self.assertEqual(git_api.inspect_repository(self.root).dirty, True)
        self.assertEqual(command('git', 'diff', '--cached', '--name-only', cwd=self.root).stdout.strip(),
                         'existing.txt')

    def test_symlink_is_reported_without_following_it(self):
        import os
        alias = self.root / 'alias.txt'
        try:
            os.symlink('existing.txt', alias)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation is not supported')
        inventory = dict(git_api.inspect_worktree(self.root).entries)
        self.assertEqual(inventory['alias.txt'].kind, 'symlink')
        self.assertEqual(inventory['alias.txt'].symlink_target, 'existing.txt')
        self.assertIsNone(inventory['alias.txt'].bytes_sha256)

    def test_subdirectory_and_detached_head_do_not_pass_repository_gate(self):
        child = self.root / 'nested'
        child.mkdir()
        with self.assertRaisesRegex(Abort, 'repository root'):
            git_api.inspect_repository(child)
        command('git', 'switch', '--detach', 'HEAD', cwd=self.root)
        with self.assertRaisesRegex(Abort, 'named branch'):
            git_api.inspect_repository(self.root)

    def test_worktree_drift_is_rejected_without_writes(self):
        (self.root / 'untracked.txt').write_text('preserve\n')
        content = (self.root / 'untracked.txt').read_bytes()
        original = gitutil.worktree_fingerprint
        calls = [0]

        def drift(root):
            calls[0] += 1
            fingerprint, paths = original(root)
            if calls[0] == 2:
                return '0' * len(fingerprint), paths
            return fingerprint, paths

        with patch.object(gitutil, 'worktree_fingerprint', side_effect=drift):
            with self.assertRaisesRegex(Abort, 'changed during read-only inspection'):
                git_api.inspect_worktree(self.root)
        self.assertEqual((self.root / 'untracked.txt').read_bytes(), content)
        self.assertEqual(command('git', 'rev-parse', 'HEAD', cwd=self.root).stdout.strip(), self.head)

    def test_change_details_remain_pure(self):
        left = {'a.txt': git_api.WorktreeEntry(' M', (), 'file', bytes_sha256='a' * 64)}
        right = {'a.txt': git_api.WorktreeEntry(' M', (), 'file', bytes_sha256='b' * 64),
                 'b.txt': git_api.WorktreeEntry('??', (), 'file', bytes_sha256='c' * 64)}
        expected = (('a.txt', ('file bytes',)), ('b.txt', ('new changed/untracked path',)))
        self.assertEqual(git_api.worktree_change_details(left, right), expected)
        self.assertEqual(left['a.txt'].bytes_sha256, 'a' * 64)
