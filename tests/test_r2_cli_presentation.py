"""R2 CLI and presentation module ownership and compatibility."""

import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PAIRS = {
    "mo_cli": ("cli_request", "cli_inspection", "help_reference"),
    "mo_presentation": ("console",),
}


class ModuleOwnershipR2Tests(unittest.TestCase):
    def test_canonical_implementation_only(self):
        package = ROOT / "apatch_lib"
        for owner, names in PAIRS.items():
            for name in names:
                with self.subTest(owner=owner, name=name):
                    self.assertTrue((package / owner / (name + ".py")).is_file())
                    self.assertFalse((package / (name + ".py")).exists())
        self.assertTrue((package / "mo_presentation" / "status.py").is_file())
        self.assertTrue((package / "status.py").is_file())

    def test_legacy_module_identity_both_import_orders(self):
        pairs = [("apatch_lib." + name, "apatch_lib." + owner + "." + name)
                 for owner, names in PAIRS.items() for name in names]
        for old_first in (True, False):
            program = (
                "import importlib\n"
                "for old, new in " + repr(pairs) + ":\n"
                "    a,b=(old,new) if " + repr(old_first) + " else (new,old)\n"
                "    x=importlib.import_module(a)\n"
                "    y=importlib.import_module(b)\n"
                "    assert x is y, (a,b)\n"
                "    assert x.__spec__.name == new\n"
            )
            result = subprocess.run([sys.executable, "-B", "-c", program],
                                    cwd=ROOT, capture_output=True, text=True,
                                    timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_contract_exports_canonical_parsing(self):
        from apatch_lib.mo_cli import api
        from apatch_lib.cli_request import parse_request
        from apatch_lib.cli_inspection import show_status_with_progress
        self.assertIs(api.parse_request, parse_request)
        self.assertIs(api.show_status_with_progress, show_status_with_progress)
        self.assertIsNone(api.parse_request(["op=STS"]).handoff)

    def test_status_rendering_keeps_read_only_evidence_owner(self):
        from apatch_lib.status import PatchStatus, display_status
        from apatch_lib.mo_presentation.status import display_recommendation
        status = PatchStatus("patch.zip", "feature/test", "synced",
                             "main", {}, None, None, "Complete")
        with patch("builtins.print") as prints:
            display_status(status)
        output = "\n".join(str(c.args[0]) for c in prints.call_args_list)
        self.assertIn("PATCH STATUS", output)
        self.assertIn("Next suggested: NONE", output)
        self.assertIsNotNone(display_recommendation)
