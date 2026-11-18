"""Standalone deployment preserves verified releases and installation-wide state."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "tools" / "deploy_apatch.py"
SPEC = importlib.util.spec_from_file_location("apatch_deployment", SOURCE)
assert SPEC is not None and SPEC.loader is not None
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


class StandaloneDeployTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.root = self.base / "installation"
        self.bin = self.base / "bin"
        self.config = self.root / "apatch.conf"
        self.addCleanup(patch.stopall)
        patch.object(DEPLOY, "INSTALL_ROOT", self.root).start()
        patch.object(DEPLOY, "CONFIG_FILE", self.config).start()
        patch.object(DEPLOY, "BIN_ROOT", self.bin).start()
        patch.object(DEPLOY, "prepare_environment").start()
        patch.object(DEPLOY, "smoke").start()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test Developer")
        self.git("config", "user.email", "developer@example.test")
        for name, text in {
            "apatch.py": "print('test')\n",
            "apatch.sh": "#!/bin/sh\nexit 0\n",
            "apatch.conf": "[apatch]\nbase_branch=main\n",
            "requirements.txt": "",
            "apatch_lib/__init__.py": "",
            "run_tests.sh": "#!/bin/sh\nexit 0\n",
        }.items():
            destination = self.source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        self.commit()

    def git(self, *args):
        completed = subprocess.run(
            ["git", "-C", str(self.source), *args], text=True,
            capture_output=True, check=True,
        )
        return completed.stdout.strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-m", "Synthetic deployment source")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        return self.git("rev-parse", "HEAD")

    def test_first_install_preserves_custom_config_and_progress(self):
        old_progress = self.source / ".apatch" / "progress"
        old_progress.mkdir(parents=True)
        (old_progress / "progress.json").write_text('{"events": []}\n')
        custom = self.base / "legacy.conf"
        custom.write_text("[apatch]\nbase_branch=develop\n")
        head = self.git("rev-parse", "HEAD")
        DEPLOY.install(str(self.source), False, str(custom))
        self.assertEqual(DEPLOY.checked_release(self.root / "current")[1], head)
        self.assertEqual(self.config.read_text(), custom.read_text())
        self.assertEqual((self.root / "releases" / head / "apatch.conf").readlink(),
                         Path("../../apatch.conf"))
        self.assertEqual((self.root / "releases" / head / ".apatch" / "progress" /
                          "progress.json").read_text(), '{"events": []}\n')
        self.assertTrue((self.bin / "apatch").is_file())
        self.assertFalse((self.source / "DEPLOY.json").exists())

    def test_upgrade_and_rollback_preserve_config_and_progress(self):
        first = self.git("rev-parse", "HEAD")
        DEPLOY.install(str(self.source), False)
        (self.root / "releases" / first / ".apatch" / "progress").mkdir(parents=True)
        (self.root / "releases" / first / ".apatch" / "progress" /
         "progress.json").write_text("first event\n")
        self.config.write_text("[apatch]\nbase_branch=stable\n")
        (self.source / "apatch.py").write_text("print('new release')\n")
        (self.source / "apatch.conf").write_text("[apatch]\nbase_branch=wrong\n")
        second = self.commit()
        DEPLOY.install(str(self.source), False)
        self.assertEqual(DEPLOY.checked_release(self.root / "current")[1], second)
        self.assertEqual(self.config.read_text(), "[apatch]\nbase_branch=stable\n")
        newer = self.root / "releases" / second / ".apatch" / "progress" / "progress.json"
        self.assertEqual(newer.read_text(), "first event\n")
        newer.write_text("second event\n")
        DEPLOY.rollback()
        self.assertEqual(DEPLOY.checked_release(self.root / "current")[1], first)
        self.assertEqual((self.root / "releases" / first / ".apatch" / "progress" /
                          "progress.json").read_text(), "second event\n")
        self.assertEqual((self.root / "releases" / first / "apatch.conf").read_text(),
                         "[apatch]\nbase_branch=stable\n")

    def test_failed_validation_preserves_current_release(self):
        first = self.git("rev-parse", "HEAD")
        DEPLOY.install(str(self.source), False)
        (self.source / "apatch.py").write_text("print('new')\n")
        self.commit()
        with patch.object(DEPLOY, "prepare_environment",
                          side_effect=DEPLOY.DeployError("test failure")):
            with self.assertRaisesRegex(DEPLOY.DeployError, "test failure"):
                DEPLOY.install(str(self.source), False)
        self.assertEqual(DEPLOY.checked_release(self.root / "current")[1], first)
        self.assertIsNone(DEPLOY.checked_release(self.root / "previous"))

    def test_explicit_config_cannot_replace_persisted_config(self):
        DEPLOY.install(str(self.source), False)
        custom = self.base / "custom.conf"
        custom.write_text("[apatch]\nbase_branch=develop\n")
        with self.assertRaisesRegex(DEPLOY.DeployError, "first installation"):
            DEPLOY.install(str(self.source), False, str(custom))

    def test_symlinked_source_config_rejected(self):
        custom = self.base / "custom.conf"
        custom.symlink_to(self.source / "apatch.conf")
        with self.assertRaisesRegex(DEPLOY.DeployError, "regular file"):
            DEPLOY.install(str(self.source), False, str(custom))
        self.assertIsNone(DEPLOY.checked_release(self.root / "current"))


if __name__ == "__main__":
    unittest.main()
