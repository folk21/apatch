"""Black-box local Git regression tests; GitHub is never contacted."""

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1]
from apatch_lib.model import Abort, RemoteOutcomeUnknown, load_handoff, load_project_config, safe_relative
from apatch_lib.patch import inspect
from apatch_lib.model import load_config
from apatch_lib.patch_history import AppliedPatchHistory
from apatch_lib.workflow import ACTION_CODES, action_number
from apatch_lib.sequence import OperationSequence, execute_sequence
from apatch_lib.workflow import outcome_label


TEST_COMMAND_TIMEOUT_SECONDS = 30


def run_bounded(argv, *, cwd, input=None, check=False,
                timeout_seconds=TEST_COMMAND_TIMEOUT_SECONDS):
    """Bound a test subprocess and its descendants without contacting real remotes."""
    command_line = [str(item) for item in argv]
    with subprocess.Popen(command_line, cwd=cwd,
                          stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          start_new_session=os.name == "posix") as process:
        try:
            stdout, stderr = process.communicate(input=input, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                stdout, stderr = exc.stdout, exc.stderr
            raise subprocess.TimeoutExpired(command_line, timeout_seconds,
                                            output=stdout, stderr=stderr) from exc
    result = subprocess.CompletedProcess(command_line, process.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result


def command(*args, cwd):
    return run_bounded(args, cwd=cwd, check=True)




class LocalGitFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML is missing from the test interpreter. Install requirements with "
                "'.venv/bin/python -m pip install -r requirements.txt' and run the tests "
                "with '.venv/bin/python -B -m unittest discover -s tests -v'."
            ) from exc

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / "tool"
        self.bin.mkdir()
        shutil.copytree(TOOL / "apatch_lib", self.bin / "apatch_lib", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(TOOL / "apatch.py", self.bin / "apatch.py")
        shutil.copy(TOOL / "apatch.sh", self.bin / "apatch.sh")
        config = (TOOL / "apatch.conf").read_text().replace("~/Downloads", str(self.base / "downloads"))
        (self.bin / "apatch.conf").write_text(config)
        (self.base / "downloads").mkdir()
        self.root = self.base / "example_service"
        self.root.mkdir()
        self.remote = self.base / "remote.git"
        command("git", "init", "--bare", str(self.remote), cwd=self.base)
        command("git", "init", "-b", "main", cwd=self.root)
        command("git", "config", "user.email", "tester@example.test", cwd=self.root)
        command("git", "config", "user.name", "Test Developer", cwd=self.root)
        command("git", "remote", "add", "origin", str(self.remote), cwd=self.root)
        (self.root / "existing.txt").write_text("old\n")
        runner = self.root / "run_checks.sh"
        runner.write_text("#!/bin/sh\nset -eu\ntest -f new.txt\n")
        runner.chmod(0o755)
        config_dir = self.root / ".apatch"
        config_dir.mkdir()
        self.log_path = config_dir / "logs" / "apatch.log"
        self.state_path = config_dir / "apply_patch.state.json"
        self.lock_path = config_dir / "apply_patch.state.json.lock"
        self.history_path = config_dir / "applied_patches.txt"
        self.project_config = config_dir / "config.yaml"
        self.project_config.write_text(
            'schema_version: 1\nlog_directory: logs\n'
            'check_timeout_seconds: 30\ncheck_idle_timeout_seconds: 30\n'
            'checks:\n  - ["./run_checks.sh"]\n')
        command("git", "add", "-A", cwd=self.root)
        command("git", "commit", "-m", "base", cwd=self.root)
        command("git", "push", "-u", "origin", "main", cwd=self.root)
        self.head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.zip = self.base / "downloads" / "example_service-PATCH-2026-10-22-11-00-test.zip"
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr("example_service/existing.txt", "updated\n")
            archive.writestr("example_service/new.txt", "new\n")
        self.params = self.base / "downloads" / "example_service_patch_params.json"
        self.payload = {
            "schema_version": 1,
            "repository": "example_service",
            "feature_branch": "feature/test-local-handoff",
            "patch_file": self.zip.name,
            "patch_sha256": hashlib.sha256(self.zip.read_bytes()).hexdigest(),
            "base_commit": self.head,
            "commit_message": "test: apply guarded patch\n\n- Add new file.\n- Update existing file."
        }
        self.params.write_text(json.dumps(self.payload))

    def prepare_test_launcher(self):
        """Retain the test interpreter's venv context when exercising the shell launcher."""
        executable = self.bin / ".venv" / "bin" / "python"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n")
        executable.chmod(0o755)

    def invoke(self, text, *options):
        if not any(option in {"--strict", "--loose", "--force"} for option in options):
            options = ("--strict", *options)
        return run_bounded([sys.executable, str(self.bin / "apatch.py"), str(self.params), *options],
                           cwd=self.root, input=text)

    def invoke_force(self, text):
        return self.invoke(text, "--force")

    def invoke_loose(self, text):
        return self.invoke(text, "--loose")

    def invoke_cli(self, *options, text=""):
        return run_bounded([sys.executable, str(self.bin / "apatch.py"), str(self.params), *options],
                           cwd=self.root, input=text)

    def make_self_contained_zip(self, *, override=None, include_metadata=True):
        """Rebuild the test patch with the verified self-contained handoff member."""
        parameters = {key: value for key, value in self.payload.items() if key != "patch_sha256"}
        parameters.update(override or {})
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr(f"{self.root.name}/existing.txt", "updated\n")
            archive.writestr(f"{self.root.name}/new.txt", "new\n")
            if include_metadata:
                archive.writestr(f"{self.root.name}/.apatch/params.json", json.dumps(parameters))
        return self.zip.stem

    def make_followup_zip(self, *, filename="example_service-PATCH-followup.zip", override=None,
                          extra_files=None):
        """Create a second real handoff for cumulative multi-ZIP sequence tests."""
        archive_path = self.base / "downloads" / filename
        payload = {key: value for key, value in self.payload.items() if key != "patch_sha256"}
        payload["patch_file"] = filename
        payload["commit_message"] = "test: combine verified patches\n\n- Include both changes."
        payload.update(override or {})
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(f"{self.root.name}/existing.txt", "second revision\n")
            archive.writestr(f"{self.root.name}/second.txt", "second patch\n")
            for relative, data in (extra_files or {}).items():
                archive.writestr(f"{self.root.name}/{relative}", data)
            archive.writestr(f"{self.root.name}/.apatch/params.json", json.dumps(payload))
        return archive_path

    def invoke_zip(self, *options, selection=None, text=""):
        arguments = ([selection] if selection is not None else []) + list(options)
        return run_bounded([sys.executable, str(self.bin / "apatch.py"), *arguments],
                           cwd=self.root, input=text)

    def assert_self_contained_lifecycle(self, mode):
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip(f"--{mode}", "op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        self.assertIn("SUCCESS", applied.stdout)
        self.assertIn("Next suggested: 1 [BRN]", applied.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        cached_path = self.root / ".apatch" / "params.json"
        cached = json.loads(cached_path.read_text())
        self.assertEqual(cached["patch_sha256"], hashlib.sha256(self.zip.read_bytes()).hexdigest())
        self.assertEqual(stat.S_IMODE(cached_path.stat().st_mode), 0o600)
        self.assertIn(".apatch/params.json", (self.root / ".git" / "info" / "exclude").read_text())
        self.assertNotIn(".apatch/params.json", command("git", "status", "--porcelain", cwd=self.root).stdout)
        blocked = self.invoke_zip(f"--{mode}", "op=CMT", "skipApproves=true")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("1 [BRN]", blocked.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        moved = self.invoke_zip(f"--{mode}", "op=BRN", "skipApproves=true")
        self.assertEqual(moved.returncode, 0, moved.stderr + moved.stdout)
        self.assertIn("Next suggested: 4 [CHK]", moved.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "feature/test-local-handoff")
        self.zip.unlink()
        verified = self.invoke_zip(f"--{mode}", "op=CHK", "skipApproves=true")
        self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)

    def configure_checks(self, yaml_text):
        self.project_config.write_text(yaml_text)
        command("git", "add", "-A", cwd=self.root)
        command("git", "commit", "-m", "Configure project verification", cwd=self.root)
        command("git", "push", cwd=self.root)
        self.head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.payload["base_commit"] = self.head
        self.params.write_text(json.dumps(self.payload))

    def assert_history(self, *, real_branch, planned_branch=None, patch_name=None):
        entries = AppliedPatchHistory(self.history_path).entries
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.patch, patch_name or self.zip.name)
        self.assertEqual(entry.planned_branch, planned_branch or self.payload["feature_branch"])
        self.assertEqual(entry.real_branch, real_branch)
        self.assertIsNotNone(datetime.fromisoformat(entry.date).tzinfo)
        self.assertIn(f"Date: {entry.date}\nPatch: {entry.patch}\n", self.history_path.read_text())
        return entry

    def write_created_registry(self, *names):
        registry = self.root / ".apatch" / "created_patches.txt"
        registry.write_text("".join(f"{name}\n" for name in names), encoding="utf-8")
        return registry

    def add_registry_member(self, content):
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr(f"{self.root.name}/.apatch/created_patches.txt", content)
        self.payload["patch_sha256"] = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))

    def assert_registry_metadata_bootstrap(self, mode):
        self.add_registry_member(self.zip.name + "\n")
        self.assertFalse((self.root / ".apatch" / "created_patches.txt").exists())
        result = self.invoke_cli(f"--{mode}", "op=BAP", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        registry = self.root / ".apatch" / "created_patches.txt"
        self.assertEqual(registry.read_text(), self.zip.name + "\n")
        state = json.loads(self.state_path.read_text())
        record = next(iter(state["workflows"].values()))
        self.assertNotIn(".apatch/created_patches.txt", record.get("changed_paths", []))
        self.assertNotIn("created_patches.txt", command("git", "status", "--porcelain",
                                                          cwd=self.root).stdout)
        self.assertTrue((self.root / "new.txt").exists())
        self.assert_history(real_branch=self.payload["feature_branch"])
