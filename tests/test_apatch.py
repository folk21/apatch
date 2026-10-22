"""Black-box local Git regression tests; GitHub is never contacted."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from apatch_lib.model import Abort, load_handoff, load_project_config, safe_relative
from apatch_lib.patch import inspect
from apatch_lib.model import load_config


def command(*args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


class LocalGitWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / "tool"
        self.bin.mkdir()
        shutil.copytree(TOOL / "apatch_lib", self.bin / "apatch_lib", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(TOOL / "apatch.py", self.bin / "apatch.py")
        config = (TOOL / "apatch.conf").read_text().replace("~/Downloads", str(self.base / "downloads"))
        (self.bin / "apatch.conf").write_text(config)
        (self.base / "downloads").mkdir()
        self.root = self.base / "signalharvester"
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
        self.project_config = config_dir / "config.yaml"
        self.project_config.write_text('schema_version: 1\nlog_directory: logs\nchecks:\n  - ["./run_checks.sh"]\n')
        command("git", "add", "-A", cwd=self.root)
        command("git", "commit", "-m", "base", cwd=self.root)
        command("git", "push", "-u", "origin", "main", cwd=self.root)
        self.head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.zip = self.base / "downloads" / "signalharvester-PATCH-2026-10-22-11-00-test.zip"
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr("signalharvester/existing.txt", "updated\n")
            archive.writestr("signalharvester/new.txt", "new\n")
        self.params = self.base / "downloads" / "signalharvester_patch_params.json"
        self.payload = {
            "schema_version": 1,
            "repository": "signalharvester",
            "feature_branch": "feature/test-local-handoff",
            "patch_file": self.zip.name,
            "patch_sha256": hashlib.sha256(self.zip.read_bytes()).hexdigest(),
            "base_commit": self.head,
            "commit_message": "test: apply guarded patch\n\n- Add new file.\n- Update existing file."
        }
        self.params.write_text(json.dumps(self.payload))

    def invoke(self, text):
        return subprocess.run([sys.executable, str(self.bin / "apatch.py"), str(self.params)],
                              cwd=self.root, input=text, capture_output=True, text=True)

    def configure_checks(self, yaml_text):
        self.project_config.write_text(yaml_text)
        command("git", "add", "-A", cwd=self.root)
        command("git", "commit", "-m", "Configure project verification", cwd=self.root)
        command("git", "push", cwd=self.root)
        self.head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.payload["base_commit"] = self.head
        self.params.write_text(json.dumps(self.payload))

    def test_project_config_is_required(self):
        self.project_config.unlink()
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing project checks config", result.stderr)

    def test_empty_and_invalid_project_checks_are_rejected(self):
        cases = [
            ("schema_version: 1\nchecks: []\n", "non-empty list"),
            ("schema_version: 1\nchecks: [42]\n", "command string or argv list"),
            ("schema_version: 1\nchecks:\n  - []\n", "invalid arguments"),
            ("schema_version: 2\nchecks:\n  - echo ok\n", "schema_version"),
            ("checks: [echo ok]\n", "schema_version and checks"),
            ("schema_version: [\n", "Invalid project checks YAML"),
        ]
        for yaml_text, reason in cases:
            with self.subTest(yaml_text=yaml_text):
                self.project_config.write_text(yaml_text)
                result = self.invoke("0\n")
                self.assertEqual(result.returncode, 2)
                self.assertIn(reason, result.stderr)

    def test_project_config_parses_multiple_commands(self):
        self.project_config.write_text(
            'schema_version: 1\nlog_directory: build/checks\nchecks:\n'
            '  - ./gradlew test\n  - ["python3", "-c", "print(42)"]\n')
        config = load_project_config(self.root, load_config(self.bin))
        self.assertEqual(config.checks, (("./gradlew", "test"), ("python3", "-c", "print(42)")))
        self.assertEqual(config.log_directory, self.root / ".apatch" / "build" / "checks")

    def test_project_config_can_run_a_nonstandard_check_script(self):
        script = self.root / "custom_verify.sh"
        script.write_text("#!/bin/sh\nset -eu\ntest -f new.txt\n")
        script.chmod(0o755)
        self.configure_checks('schema_version: 1\nchecks:\n  - ["./custom_verify.sh"]\n')
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        result = self.invoke("4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log_path.read_text()
        self.assertIn("./custom_verify.sh", log)
        self.assertNotIn("./run_checks.sh", log)

    def test_project_check_output_is_visible_and_saved_to_project_log(self):
        script = self.root / "custom_verify.sh"
        script.write_text("#!/bin/sh\nset -eu\nprintf 'CHECK STDOUT\\n'\n"
                          "printf 'CHECK STDERR\\n' >&2\ntest -f new.txt\n")
        script.chmod(0o755)
        self.configure_checks('schema_version: 1\nchecks:\n  - ["./custom_verify.sh"]\n')
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        result = self.invoke("4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CHECK STDOUT", result.stdout)
        self.assertIn("CHECK STDERR", result.stdout)
        self.assertIn("check output: CHECK STDOUT", self.log_path.read_text())
        self.assertIn("check output: CHECK STDERR", self.log_path.read_text())
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         " M existing.txt\n?? new.txt\n")

    def test_menu_lists_every_action_even_when_git_state_blocks_actions(self):
        (self.root / "untracked.txt").write_text("dirty\n")
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"\n-----\nRepository: {self.root}\n"
                      f"Feature branch: {self.payload['feature_branch']}\n"
                      f"Patch: {self.zip.name}\nPhase: new\n"
                      "Current branch: main\n-----\n", result.stdout)
        expected_labels = [
            "Create a feature branch",
            "Create a feature branch and apply patch",
            "Apply patch to current branch (main)",
            "Run/re-run canonical checks",
            "Commit and push all verified changes",
            "Retry push of the existing commit",
            "Create/find PR",
            "Merge PR into",
            "Resume synchronization of local",
        ]
        for index, label in enumerate(expected_labels, start=1):
            self.assertIn(f" {index}. {label}", result.stdout)
        self.assertIn(" 0. Exit", result.stdout)
        self.assertIn("requires a clean working tree", result.stdout)

    def test_unavailable_action_reports_reason_without_mutating_git(self):
        (self.root / "untracked.txt").write_text("dirty\n")
        result = self.invoke("1\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Action unavailable: requires a clean working tree", result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        self.assertFalse((self.root / "new.txt").exists())

    def test_apply_patch_to_main_and_verify_without_creating_feature_branch(self):
        menu = self.invoke("0\n")
        self.assertEqual(menu.returncode, 0, menu.stderr)
        self.assertIn(" 3. Apply patch to current branch (main)\n", menu.stdout)
        applied = self.invoke("3\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Apply", applied.stdout)
        self.assertIn("to main?", applied.stdout)
        self.assertIn("Patch applied", applied.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")
        self.assertFalse(command("git", "branch", "--list", self.payload["feature_branch"],
                                 cwd=self.root).stdout.strip())
        state = json.loads((self.bin / "signalharvester_apply_patch.state.json").read_text())
        self.assertEqual(next(iter(state["workflows"].values()))["applied_branch"], "main")
        verified = self.invoke("4\n")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("Canonical checks passed", verified.stdout)
        blocked = self.invoke("5\n")
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn("patch was applied to main", blocked.stderr)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)

    def test_apply_patch_to_another_checked_out_branch(self):
        command("git", "switch", "-c", "release/manual-patch", cwd=self.root)
        command("git", "commit", "--allow-empty", "-m", "release baseline", cwd=self.root)
        self.payload.pop("base_commit")
        self.params.write_text(json.dumps(self.payload))
        menu = self.invoke("0\n")
        self.assertIn("Apply patch to current branch (release/manual-patch)", menu.stdout)
        applied = self.invoke("3\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("to release/manual-patch?", applied.stdout)
        verified = self.invoke("4\n")
        self.assertEqual(verified.returncode, 0, verified.stderr)

    def test_apply_patch_to_main_after_feature_branch_was_created(self):
        created = self.invoke("1\nYES\n")
        self.assertEqual(created.returncode, 0, created.stderr)
        command("git", "switch", "main", cwd=self.root)
        menu = self.invoke("0\n")
        self.assertIn(" 3. Apply patch to current branch (main)\n", menu.stdout)
        applied = self.invoke("3\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(self.invoke("4\n").returncode, 0)

    def test_patch_branch_restriction_can_be_enabled_in_config(self):
        conf = self.bin / "apatch.conf"
        conf.write_text(conf.read_text().replace("require_patch_feature_branch = false",
                                                "require_patch_feature_branch = true"))
        menu = self.invoke("0\n")
        self.assertIn(" 3. Apply patch to current branch (main) * (requires current branch: "
                      + self.payload["feature_branch"] + ")", menu.stdout)
        blocked = self.invoke("3\n")
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn("Action unavailable: requires current branch", blocked.stderr)
        self.assertFalse((self.root / "new.txt").exists())

    def test_patch_menu_disables_detached_head(self):
        command("git", "switch", "--detach", "HEAD", cwd=self.root)
        menu = self.invoke("0\n")
        self.assertIn("Apply patch to current branch (detached HEAD)", menu.stdout)
        self.assertIn("requires a checked-out branch", menu.stdout)
        blocked = self.invoke("3\n")
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn("requires a checked-out branch", blocked.stderr)

    def test_applied_patch_history_created_only_after_success(self):
        history = self.bin / "signalharvester_applied_patches.txt"
        self.assertFalse(history.exists())
        cancelled = self.invoke("2\nYES\nno\n")
        self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
        self.assertFalse(history.exists() and history.read_text().strip())
        result = self.invoke("3\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(history.read_text(), self.zip.name + "\n")
        self.assertEqual(stat.S_IMODE(history.stat().st_mode), 0o600)

    def test_previously_applied_patch_warns_and_requires_yes_no(self):
        history = self.bin / "signalharvester_applied_patches.txt"
        history.write_text(self.zip.name + "\n")
        denied = self.invoke("2\nno\n")
        self.assertEqual(denied.returncode, 0, denied.stderr)
        self.assertIn("WARNING: Patch", denied.stdout)
        self.assertIn("already in the applied-patch history", denied.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        self.assertFalse((self.root / "new.txt").exists())
        invalid = self.invoke("2\nperhaps\n")
        self.assertEqual(invalid.returncode, 2, invalid.stderr)
        self.assertIn("Expected yes or no", invalid.stderr)
        accepted = self.invoke("2\nyes\nYES\nYES\n")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("Patch applied", accepted.stdout)
        self.assertEqual(history.read_text().count(self.zip.name), 1)
        log = self.log_path.read_text()
        self.assertIn("developer approved previously applied patch reapplication", log)

    def test_repeated_patch_on_existing_branch_warns(self):
        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        history = self.bin / "signalharvester_applied_patches.txt"
        history.write_text(self.zip.name + "\n")
        denied = self.invoke("3\nno\n")
        self.assertEqual(denied.returncode, 0, denied.stderr)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        accepted = self.invoke("3\nyes\nYES\n")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("Patch applied", accepted.stdout)

    def test_local_branch_already_exists_even_when_not_checked_out(self):
        command("git", "branch", self.payload["feature_branch"], cwd=self.root)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")
        result = self.invoke("1\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("already exists locally", result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")

    def test_remote_branch_already_exists_even_when_not_local(self):
        command("git", "push", "origin", f"HEAD:refs/heads/{self.payload['feature_branch']}", cwd=self.root)
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("already exists on origin", result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")

    def test_remote_base_head_mismatch_prevents_branch_creation(self):
        command("git", "commit", "--allow-empty", "-m", "local only", cwd=self.root)
        self.payload["base_commit"] = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.params.write_text(json.dumps(self.payload))
        result = self.invoke("1\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Local base HEAD differs", result.stderr)

    def test_corrupt_patch_history_rejects_without_branch_creation(self):
        history = self.bin / "signalharvester_applied_patches.txt"
        history.write_text("invalid/entry.zip\n")
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("history contains an invalid entry", result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")

    def test_history_path_inside_repository_rejected(self):
        conf = self.bin / "apatch.conf"
        conf.write_text(conf.read_text().replace("applied_patches_file = signalharvester_applied_patches.txt",
                                                f"applied_patches_file = {self.root / 'patches.txt'}"))
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("history must be outside the Git repository", result.stderr)
        self.assertFalse((self.root / "patches.txt").exists())

    def test_symlink_patch_history_is_rejected(self):
        protected = self.base / "protected.txt"
        protected.write_text("original")
        (self.bin / "signalharvester_applied_patches.txt").symlink_to(protected)
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("History destination must be a regular file", result.stderr)
        self.assertEqual(protected.read_text(), "original")

    def test_remote_url_drift_blocks_commit(self):
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        self.assertEqual(self.invoke("4\n").returncode, 0)
        other_remote = self.base / "other.git"
        command("git", "init", "--bare", str(other_remote), cwd=self.base)
        command("git", "remote", "set-url", "origin", str(other_remote), cwd=self.root)
        result = self.invoke("5\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("remote URL has changed", result.stderr)
        self.assertEqual(command("git", "log", "-1", "--format=%s", cwd=self.root).stdout.strip(), "base")

    def test_remote_feature_appearing_after_local_creation_blocks_push(self):
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        self.assertEqual(self.invoke("4\n").returncode, 0)
        command("git", "push", "origin", f"{self.head}:refs/heads/{self.payload['feature_branch']}",
                cwd=self.root)
        result = self.invoke("5\nYES\nYES\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unexpected history", result.stderr)
        self.assertEqual(command("git", "log", "-1", "--format=%s", cwd=self.root).stdout.strip(),
                         "test: apply guarded patch")
        state = json.loads((self.bin / "signalharvester_apply_patch.state.json").read_text())
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "committed")

    def test_history_lock_rejects_concurrent_use(self):
        from apatch_lib.patch_history import locked_history
        path = self.bin / "signalharvester_applied_patches.txt"
        with locked_history(path) as history:
            self.assertFalse(history.contains(self.zip.name))
            with self.assertRaises(Abort):
                with locked_history(path):
                    pass
            history.append(self.zip.name)
        with locked_history(path) as history:
            self.assertTrue(history.contains(self.zip.name))
            history.append(self.zip.name)
        self.assertEqual(path.read_text(), self.zip.name + "\n")

    def test_full_local_workflow_and_repeated_menu(self):
        result = self.invoke("2\nYES\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Patch applied", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])
        result = self.invoke("4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Canonical checks passed", result.stdout)
        result = self.invoke("5\nYES\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Commit and push verified", result.stdout)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        changed = command("git", "show", "--pretty=", "--name-only", "HEAD", cwd=self.root).stdout.splitlines()
        self.assertEqual(set(changed), {"existing.txt", "new.txt"})
        self.assertIn("Add new file.", command("git", "log", "-1", "--format=%B", cwd=self.root).stdout)
        self.assertIn("Create/find PR", self.invoke("0\n").stdout)
        state = json.loads((self.bin / "signalharvester_apply_patch.state.json").read_text())
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "pushed")

    def test_log_records_patch_identity_and_commit_body_only_on_commit(self):
        self.payload["commit_message"] += "\nSecret-in-commit-body-should-not-be-logged"
        self.params.write_text(json.dumps(self.payload))
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        self.assertEqual(self.invoke("4\n").returncode, 0)
        self.assertEqual(self.invoke("5\nYES\nYES\n").returncode, 0)
        target = self.log_path
        self.assertTrue(target.is_file())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        content = target.read_text(encoding="utf-8")
        self.assertIn("command start", content)
        self.assertIn("git switch -c feature/test-local-handoff", content)
        self.assertIn("git -c core.quotePath=false status --porcelain=v1", content)
        self.assertIn("./run_checks.sh", content)
        self.assertIn("git commit -F -", content)
        self.assertIn("git push -u origin feature/test-local-handoff", content)
        self.assertIn("checkpoint saved feature=feature/test-local-handoff phase=pushed", content)
        self.assertIn("command finished exit=0", content)
        lines = content.splitlines()
        self.assertTrue(lines)
        for line in lines:
            self.assertIn(f"patch={self.zip.name}", line)
            self.assertIn("branch=feature/test-local-handoff", line)
            self.assertRegex(line, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4} ")
        self.assertEqual(content.count("Secret-in-commit-body-should-not-be-logged"), 1)
        self.assertIn('git commit -F - commit_message=',
                      next(line for line in lines if "Secret-in-commit-body-should-not-be-logged" in line))

    def test_nonzero_exit_and_stop_are_logged(self):
        self.configure_checks(
            'schema_version: 1\nchecks:\n  - ["./run_checks.sh"]\n'
            '  - ["python3", "-c", "print(\'CHECK BEFORE FAILURE\'); raise SystemExit(17)"]\n')
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        failed = self.invoke("4\n")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("Command failed (17)", failed.stderr)
        self.assertIn("CHECK BEFORE FAILURE", failed.stdout)
        content = self.log_path.read_text()
        self.assertIn("check output: CHECK BEFORE FAILURE", content)
        self.assertIn("command finished exit=17", content)
        self.assertIn("invocation stopped: Command failed (17)", content)
        self.assertNotIn("Traceback", content)

    def test_project_log_directory_is_relative_to_project_apatch(self):
        custom = self.root / ".apatch" / "custom" / "checks"
        self.project_config.write_text(
            'schema_version: 1\nlog_directory: custom/checks\nchecks:\n  - ./run_checks.sh\n')
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((custom / "apatch.log").exists())
        self.assertFalse((self.bin / "logs").exists())
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, " M .apatch/config.yaml\n")

    def test_global_log_directory_is_resolved_from_project_apatch(self):
        conf = self.bin / "apatch.conf"
        conf.write_text(conf.read_text().replace("log_directory = logs", "log_directory = runtime/logs"))
        self.project_config.write_text('schema_version: 1\nchecks:\n  - ./run_checks.sh\n')
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / ".apatch" / "runtime" / "logs" / "apatch.log").exists())

    def test_absolute_or_parent_log_paths_are_rejected(self):
        for path in ("/tmp/unwanted", "../escape", "logs/../escape", "~/.cache", ""):
            with self.subTest(path=path):
                self.project_config.write_text(
                    f'schema_version: 1\nlog_directory: "{path}"\nchecks:\n  - ./run_checks.sh\n')
                result = self.invoke("0\n")
                self.assertEqual(result.returncode, 2)
                self.assertIn("relative path inside the project .apatch", result.stderr)
        self.assertFalse(self.log_path.exists())

    def test_absolute_global_log_path_rejected(self):
        conf = self.bin / "apatch.conf"
        conf.write_text(conf.read_text().replace("log_directory = logs", f"log_directory = {self.base}"))
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("relative path inside the project .apatch", result.stderr)

    def test_project_logs_are_automatically_ignored_only_locally(self):
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.log_path.is_file())
        self.assertIn(str(self.log_path), result.stdout)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        self.assertEqual(command("git", "check-ignore", ".apatch/logs/apatch.log",
                                 cwd=self.root).stdout.strip(), ".apatch/logs/apatch.log")
        info_exclude = (self.root / ".git" / "info" / "exclude").read_text()
        self.assertIn("/.apatch/logs/", info_exclude)
        self.assertEqual(self.invoke("0\n").returncode, 0)
        self.assertEqual((self.root / ".git" / "info" / "exclude").read_text(), info_exclude)

    def test_existing_log_symlink_is_rejected(self):
        log_dir = self.root / ".apatch" / "logs"
        log_dir.mkdir()
        target = self.base / "protected.txt"
        target.write_text("protected")
        (log_dir / "apatch.log").symlink_to(target)
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Log destination must be a regular file", result.stderr)
        self.assertEqual(target.read_text(), "protected")

    def test_symlink_in_log_subdirectory_is_rejected(self):
        (self.root / ".apatch" / "logs").symlink_to(self.base, target_is_directory=True)
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Log directory must not contain symlinks", result.stderr)

    def test_symlinked_git_exclude_is_rejected_without_overwriting_target(self):
        exclude = self.root / ".git" / "info" / "exclude"
        protected = self.base / "protected-excludes.txt"
        protected.write_text("unchanged\n")
        exclude.unlink()
        exclude.symlink_to(protected)
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsafe local Git exclude file", result.stderr)
        self.assertEqual(protected.read_text(), "unchanged\n")
        self.assertFalse(self.log_path.exists())

    def test_unverified_changed_bytes_cannot_be_committed(self):
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        self.assertEqual(self.invoke("4\n").returncode, 0)
        (self.root / "new.txt").write_text("tampered\n")
        result = self.invoke("5\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("verified bytes", result.stderr)

    def test_unexpected_untracked_file_blocks_verification(self):
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        (self.root / "surprise.txt").write_text("unexpected")
        result = self.invoke("4\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unexpected changed files", result.stderr)

    def test_wrong_baseline_rejected_before_branch_creation(self):
        self.payload["base_commit"] = "a" * 40
        self.params.write_text(json.dumps(self.payload))
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Base HEAD mismatch", result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")

    def test_path_traversal_rejected_without_extracting(self):
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr("signalharvester/../escaped", "bad")
        self.payload["patch_sha256"] = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsafe path", result.stderr)
        self.assertFalse((self.base / "escaped").exists())

    def test_symlink_zip_member_rejected(self):
        with zipfile.ZipFile(self.zip, "w") as archive:
            info = zipfile.ZipInfo("signalharvester/link")
            info.create_system = 3
            info.external_attr = (0o120777 << 16)
            archive.writestr(info, "../../etc/passwd")
        self.payload["patch_sha256"] = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsupported ZIP file type", result.stderr)

    def test_deletion_from_handoff_is_part_of_commit(self):
        self.payload["delete_paths"] = ["existing.txt"]
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr("signalharvester/new.txt", "new\n")
        self.payload["patch_sha256"] = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        result = self.invoke("4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.invoke("5\nYES\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        status = command("git", "show", "--pretty=", "--name-status", "HEAD", cwd=self.root).stdout
        self.assertIn("D\texisting.txt", status)
        self.assertIn("A\tnew.txt", status)


class ValidationTest(unittest.TestCase):
    def test_relative_paths(self):
        for value in ["../foo", "x/../y", "x/.git/config", "/tmp/file", "x//y", "x\\y"]:
            with self.subTest(value=value), self.assertRaises(Abort):
                safe_relative(value)

    def test_command_line_logging_redacts_secret_arguments(self):
        from apatch_lib.gitutil import display_command
        rendered = display_command(["gh", "pr", "create", "--body", "confidential-body",
                                    "--token=secret-token", "--password", "secret-password"])
        self.assertIn("--body '[REDACTED]'", rendered)
        self.assertIn("'--token=[REDACTED]'", rendered)
        self.assertNotIn("confidential-body", rendered)
        self.assertNotIn("secret-token", rendered)
        self.assertNotIn("secret-password", rendered)

    def test_reject_paths_in_patch_basename(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "params.json"
            path.write_text(json.dumps({"schema_version": 1, "repository": "signalharvester",
                                        "feature_branch": "feature/test", "patch_file": "../patch.zip",
                                        "commit_message": "test: msg"}))
            with self.assertRaises(Abort):
                load_handoff(path)


if __name__ == "__main__":
    unittest.main()

class GithubGuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.branch = "feature/a"
        self.sha = "a" * 40
        from apatch_lib.model import Config, Handoff
        self.config = Config(self.root, self.root / "state.json", self.root / "logs", self.root / "history.txt", "origin", "main",
                             (("./run_checks.sh",),), True, True, "merge", 10000)
        self.handoff = Handoff("signalharvester", self.branch, "patch.zip", "test: message\n", None, None, ())
        self.record = {"phase": "pr_created", "pushed_sha": self.sha, "pr_number": 4}
        self.details = {"number": 4, "state": "OPEN", "headRefName": self.branch,
                        "baseRefName": "main", "headRefOid": self.sha,
                        "url": "https://github.com/example/repo/pull/4", "reviewDecision": "APPROVED",
                        "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
                        "statusCheckRollup": [{"name": "test", "conclusion": "SUCCESS"}], "mergedAt": None}

    def run_guard(self, *, approval=None, check=None, sha=None):
        from unittest.mock import patch
        from apatch_lib import github
        payload = dict(self.details)
        if approval is not None:
            payload["reviewDecision"] = approval
        if check is not None:
            payload["statusCheckRollup"] = [{"name": "test", "conclusion": check}]
        if sha is not None:
            payload["headRefOid"] = sha
        with patch.object(github, "require_clean"), patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[dict(self.details)]), \
             patch.object(github, "pr_details", return_value=payload), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "run") as fake_run, \
             patch.object(github, "confirm", return_value=True):
            try:
                github.merge_pr(self.config, self.handoff, self.root, self.record, lambda: None)
            except Abort as error:
                self.assertFalse(any("merge" in str(call) for call in fake_run.call_args_list))
                return str(error)
        raise AssertionError("Expected merge to be rejected")

    def test_pending_check_blocks_merge(self):
        self.assertIn("pending checks", self.run_guard(check="PENDING"))

    def test_missing_approval_blocks_merge(self):
        self.assertIn("not approved", self.run_guard(approval="REVIEW_REQUIRED"))

    def test_pr_head_drift_blocks_merge(self):
        self.assertIn("drifted", self.run_guard(sha="b" * 40))

    def test_clean_approved_pr_permits_guarded_merge(self):
        from unittest.mock import patch
        from apatch_lib import github
        after = dict(self.details, state="MERGED", mergedAt="2026-10-22T10:00:00Z")
        with patch.object(github, "require_clean"), patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", return_value=[dict(self.details)]), \
             patch.object(github, "pr_details", side_effect=[dict(self.details), after]), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "run") as fake_run, \
             patch.object(github, "confirm", return_value=True):
            github.merge_pr(self.config, self.handoff, self.root, self.record, lambda: None)
        self.assertEqual(self.record["phase"], "merged")
        self.assertTrue(any(call.args[0][:3] == ["gh", "pr", "merge"] for call in fake_run.call_args_list))

    def test_new_pr_created_without_attempting_merge(self):
        from unittest.mock import patch
        from apatch_lib import github
        record = {"phase": "pushed", "pushed_sha": self.sha}
        created = {"number": 4, "state": "OPEN", "headRefName": self.branch,
                   "baseRefName": "main", "headRefOid": self.sha, "url": self.details["url"]}
        with patch.object(github, "require_clean"), patch.object(github, "head", return_value=self.sha), \
             patch.object(github, "repository", return_value="example/repo"), \
             patch.object(github, "pr_list", side_effect=[[], [created]]), \
             patch.object(github, "remote_head", return_value=self.sha), \
             patch.object(github, "output", return_value="[]"), \
             patch.object(github, "run") as fake_run, \
             patch.object(github, "confirm", return_value=True):
            github.create_pr(self.config, self.handoff, self.root, record, lambda: None)
        self.assertEqual(record["phase"], "pr_created")
        self.assertEqual(record["pr_number"], 4)
        self.assertTrue(any(call.args[0][:3] == ["gh", "pr", "create"] for call in fake_run.call_args_list))
        self.assertFalse(any(call.args[0][:3] == ["gh", "pr", "merge"] for call in fake_run.call_args_list))
