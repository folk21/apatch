"""R3.6 typed handoff cache and backward-compatibility checks."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apatch_lib.mo_core.api import Abort
from apatch_lib.mo_handoff.api import HandoffCacheOperations, ProjectHandoffCache
from apatch_lib.mo_handoff.models import Handoff
from apatch_lib.mo_handoff.cache.service import RecoverableCacheError
from apatch_lib import params_cache
from apatch_lib.handoff_selection import HandoffSelection, SelectionKind, resolve_selected_handoff
from apatch_lib.cli_request import parse_request
from apatch_lib.application import ProjectContext, execute_request
from tests._support import LocalGitFixture, command


class HandoffCacheBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "example"
        (self.root / ".apatch").mkdir(parents=True)
        self.handoff = Handoff(
            repository="example", branch="feature/cache-r36",
            patch="example-PATCH-2026-11-18-21-20-cache.zip",
            message="refactor: cache boundary\n\nPreserve validated cache semantics.\n",
            base_commit=None, patch_sha256="a" * 64, delete_paths=(),
        )

    def test_cold_imports_and_legacy_function_identity(self):
        script_root = Path(__file__).resolve().parents[1]
        commands = (
            "from apatch_lib.params_cache import load_cached_handoff; "
            "from apatch_lib.mo_handoff.api import HandoffCacheOperations, ProjectHandoffCache",
            "from apatch_lib.mo_handoff.api import ProjectHandoffCache; "
            "from apatch_lib.handoff_selection import resolve_selected_handoff; "
            "from apatch_lib.params_cache import save_cached_handoff",
            "from apatch_lib.mo_handoff.cache.service import save_cached_handoff; "
            "from apatch_lib.model import Handoff",
        )
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run([sys.executable, "-B", "-c", command],
                                        cwd=script_root, text=True, capture_output=True,
                                        timeout=15, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
        from apatch_lib.mo_handoff.cache import service
        self.assertIs(params_cache.load_cached_handoff, service.load_cached_handoff)
        self.assertIs(params_cache.save_cached_handoff, service.save_cached_handoff)
        self.assertIs(params_cache.RecoverableCacheError, service.RecoverableCacheError)
        self.assertIsInstance(ProjectHandoffCache(), HandoffCacheOperations)

    def test_cache_roundtrip_uses_identical_schema_and_stable_lock(self):
        cache = ProjectHandoffCache()
        cache.preflight_write(self.root)
        self.assertFalse((self.root / ".apatch" / "params.json.lock").exists())
        cache.save(self.root, self.handoff)
        stored = self.root / ".apatch" / "params.json"
        data = json.loads(stored.read_text())
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["patch_sha256"], "a" * 64)
        self.assertEqual(cache.load(self.root), self.handoff)
        self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
        self.assertTrue(stored.with_name("params.json.lock").exists())

    def test_invalid_cache_is_backed_up_before_replacement(self):
        stored = self.root / ".apatch" / "params.json"
        stored.write_text('{"schema_version":1,"repository":"other"}')
        original = stored.read_bytes()
        cache = ProjectHandoffCache()
        with self.assertRaises(RecoverableCacheError):
            cache.load(self.root)
        cache.preflight_write(self.root)
        self.assertEqual(stored.read_bytes(), original)
        cache.save(self.root, self.handoff)
        self.assertEqual(cache.load(self.root), self.handoff)
        backups = list((self.root / ".apatch" / "backups").glob("params-invalid-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)

    def test_symlinked_target_fails_before_writes(self):
        victim = self.root / "victim.json"
        victim.write_text("untouched")
        (self.root / ".apatch" / "params.json").symlink_to(victim)
        with self.assertRaisesRegex(Abort, "Unsafe cached handoff path"):
            ProjectHandoffCache().preflight_write(self.root)
        self.assertEqual(victim.read_text(), "untouched")
        self.assertFalse((self.root / ".apatch" / "params.json.lock").exists())

    def test_readonly_selection_consumes_injected_protocol(self):
        fake = Mock(spec=HandoffCacheOperations)
        fake.load.return_value = self.handoff
        selection = resolve_selected_handoff(None, SimpleNamespace(), self.root,
                                             cache_ops=fake)
        self.assertEqual(selection.handoff, self.handoff)
        fake.load.assert_called_once_with(self.root)
        fake.preflight_write.assert_not_called()
        fake.save.assert_not_called()
        with patch("apatch_lib.handoff_selection.load_cached_handoff", side_effect=AssertionError):
            selection = resolve_selected_handoff(None, SimpleNamespace(), self.root,
                                                 cache_ops=fake)
            self.assertEqual(selection.handoff, self.handoff)

    def test_unverified_repository_identity_rejected(self):
        mismatched = Handoff(
            repository="other", branch=self.handoff.branch, patch=self.handoff.patch,
            message=self.handoff.message, base_commit=None,
            patch_sha256=self.handoff.patch_sha256, delete_paths=(),
        )
        with self.assertRaisesRegex(Abort, "verified identity and digest"):
            ProjectHandoffCache().save(self.root, mismatched)
        self.assertFalse((self.root / ".apatch" / "params.json.lock").exists())

    def test_cli_lifecycle_receives_injected_cache_port(self):
        cache = Mock(spec=HandoffCacheOperations)
        selection = HandoffSelection(self.handoff, "selected ZIP", SelectionKind.NEW_ZIP)
        context = ProjectContext(self.root, SimpleNamespace(), self.root)
        request = parse_request(["op=APL"])
        with (patch("apatch_lib.application.load_config", return_value=object()),
              patch("apatch_lib.application._resolve_project", return_value=context),
              patch("apatch_lib.application.resolve_handoffs", return_value=selection) as resolve,
              patch("apatch_lib.application._admit_zip_start", return_value=(False, False)),
              patch("apatch_lib.application._execute_lifecycle") as lifecycle):
            self.assertEqual(execute_request(request, self.root, cache_ops=cache), 0)
        resolve.assert_called_once_with(request, context.config, self.root, cache_ops=cache)
        lifecycle.assert_called_once()
        self.assertIs(lifecycle.call_args.kwargs["cache_ops"], cache)
        cache.preflight_write.assert_called_once_with(self.root)
        cache.save.assert_not_called()


class HandoffCacheCliRegressionTests(LocalGitFixture):
    def test_new_zip_apl_and_cached_brn_run_through_real_cli(self):
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        self.assertIn("RESULT 3 [APL]: SUCCESS", applied.stdout)
        cached = self.root / ".apatch" / "params.json"
        self.assertTrue(cached.is_file())
        branched = self.invoke_zip("op=BRN", "skipApproves=true")
        self.assertEqual(branched.returncode, 0, branched.stderr + branched.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])
