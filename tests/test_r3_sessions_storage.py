"""R3 persistence and feature-session ownership without changed workflow behavior."""

import importlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OWNERS = {
    "mo_feature_sessions": ("session", "session_continuation", "commit_scope", "context"),
    "mo_storage": ("state", "operation_events", "progress", "migration",
                   "local_ignore", "logging_setup"),
}


class R3OwnershipTests(unittest.TestCase):
    def test_implementation_is_under_single_module_owner(self):
        for owner, filenames in OWNERS.items():
            for name in filenames:
                with self.subTest(owner=owner, name=name):
                    self.assertTrue((ROOT / "apatch_lib" / owner / (name + ".py")).is_file())
                    self.assertFalse((ROOT / "apatch_lib" / (name + ".py")).exists())
        for owner in OWNERS:
            self.assertTrue((ROOT / "apatch_lib" / owner / "api.py").is_file())
            self.assertTrue((ROOT / "apatch_lib" / owner / "contract.md").is_file())

    def test_legacy_import_identity_in_both_orders(self):
        pairs = [(f"apatch_lib.{name}", f"apatch_lib.{owner}.{name}")
                 for owner, names in OWNERS.items() for name in names]
        for old_first in (True, False):
            script = (
                "import importlib\n"
                "for old, new in " + repr(pairs) + ":\n"
                "    first, second = (old, new) if " + repr(old_first) + " else (new, old)\n"
                "    x = importlib.import_module(first)\n"
                "    y = importlib.import_module(second)\n"
                "    assert x is y, (first, second)\n"
                "    assert y.__spec__.name == new, y.__spec__\n"
            )
            result = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=ROOT,
                capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_api_and_legacy_patch_targets_are_shared(self):
        from apatch_lib.mo_feature_sessions.api import FeatureSession, validate_feature_sessions
        from apatch_lib.mo_storage.api import OperationRun, read_state_snapshot
        from apatch_lib.session import FeatureSession as OldFeatureSession
        from apatch_lib.session import validate_feature_sessions as old_validate
        from apatch_lib.operation_events import OperationRun as OldRun
        from apatch_lib.state import read_state_snapshot as old_read
        self.assertIs(FeatureSession, OldFeatureSession)
        self.assertIs(validate_feature_sessions, old_validate)
        self.assertIs(OperationRun, OldRun)
        self.assertIs(read_state_snapshot, old_read)
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "missing.json"
            self.assertEqual(read_state_snapshot(path)["workflows"], {})
            self.assertFalse(path.exists())
        with patch("apatch_lib.state.os.replace", side_effect=OSError("simulated")) as replaced:
            from apatch_lib.mo_storage import state
            self.assertIs(state.os.replace, replaced)

    def test_storage_state_import_does_not_initialize_session_services(self):
        script = (
            "import sys\n"
            "import apatch_lib.mo_storage.state\n"
            "assert 'apatch_lib.mo_feature_sessions.validation' in sys.modules\n"
            "assert 'apatch_lib.mo_feature_sessions.session' not in sys.modules\n"
            "assert 'apatch_lib.mo_feature_sessions.context' not in sys.modules\n"
            "import apatch_lib.mo_feature_sessions.api\n"
            "assert 'apatch_lib.mo_feature_sessions.session' in sys.modules\n"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=ROOT,
            capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_persisted_unknown_session_reference_still_fails_closed(self):
        from apatch_lib.mo_storage.state import _upgrade_and_validate
        from apatch_lib.model import Abort
        payload = {"schema_version": 2, "workflows": {}, "operation_runs": [],
                   "feature_sessions": {"invalid-id": {}}}
        with self.assertRaises(Abort):
            _upgrade_and_validate(payload)
        self.assertEqual(payload["feature_sessions"], {"invalid-id": {}})
