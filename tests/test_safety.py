"""Regression tests for the safety subsystem."""

import time

from tests._support import (
    LocalGitFixture, command, TOOL, hashlib,
    json, os, re, shlex,
    shutil, stat, subprocess, sys,
    tempfile, unittest, zipfile, redirect_stdout,
    replace, datetime, StringIO, Path,
    patch, Abort, RemoteOutcomeUnknown, load_handoff,
    load_project_config, safe_relative, inspect, load_config,
    AppliedPatchHistory, ACTION_CODES, action_number, OperationSequence,
    execute_sequence, outcome_label,
)


class SafetyTests(LocalGitFixture):
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

    def test_nonzero_exit_and_failure_diagnostics_are_logged(self):
        self.configure_checks(
            'schema_version: 1\nchecks:\n  - ["./run_checks.sh"]\n'
            '  - ["python3", "-c", "print(\'CHECK BEFORE FAILURE\'); raise SystemExit(17)"]\n')
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        failed = self.invoke("4\n")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("Command failed (17)", failed.stderr)
        self.assertIn("CHECK BEFORE FAILURE", failed.stdout)
        content = self.log_path.read_text()
        self.assertIn("check command failed exit=17", content)
        self.assertIn('recent_output="CHECK BEFORE FAILURE"', content)
        self.assertIn("invocation stopped: Command failed (17)", content)
        self.assertNotIn("Traceback", content)

    def test_failed_check_logs_only_bounded_recent_output(self):
        script = self.root / "verbose_checks.py"
        script.write_text(
            "import sys\n"
            "print('PROGRESS BEFORE ERROR')\n"
            "for i in range(40):\n"
            "    print(f'step-{i}')\n"
            "print('FAILURE DETAIL')\n"
            "sys.exit(9)\n")
        self.configure_checks(
            'schema_version: 1\nchecks:\n'
            '  - ["python3", "verbose_checks.py"]\n')
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        failed = self.invoke("4\n")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("PROGRESS BEFORE ERROR", failed.stdout)
        self.assertIn("FAILURE DETAIL", failed.stdout)
        log = self.log_path.read_text()
        self.assertIn("check command failed exit=9", log)
        self.assertIn("FAILURE DETAIL", log)
        self.assertNotIn("PROGRESS BEFORE ERROR", log)
        self.assertNotIn("step-0\\n", log)

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
        self.assertTrue(self.lock_path.is_file())
        self.assertFalse(self.state_path.exists())
        self.assertIn(str(self.log_path), result.stdout)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        self.assertEqual(command("git", "check-ignore", ".apatch/logs/apatch.log",
                                 cwd=self.root).stdout.strip(), ".apatch/logs/apatch.log")
        info_exclude = (self.root / ".git" / "info" / "exclude").read_text()
        self.assertIn("/.apatch/logs/", info_exclude)
        for file in (self.state_path, self.lock_path, self.history_path):
            relative = file.relative_to(self.root).as_posix()
            self.assertIn(f"/{relative}", info_exclude)
            self.assertEqual(command("git", "check-ignore", relative, cwd=self.root).stdout.strip(),
                             relative)
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

    def test_symlinked_state_and_lock_files_are_rejected(self):
        for path in (self.state_path, self.lock_path):
            with self.subTest(path=path):
                protected = self.base / "protected-state.txt"
                protected.write_text("unchanged\n")
                path.symlink_to(protected)
                result = self.invoke("0\n")
                self.assertEqual(result.returncode, 2)
                self.assertIn("Runtime state and history files must not be symlinks", result.stderr)
                self.assertEqual(protected.read_text(), "unchanged\n")
                path.unlink()

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
            archive.writestr("example_service/../escaped", "bad")
        self.payload["patch_sha256"] = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsafe path", result.stderr)
        self.assertFalse((self.base / "escaped").exists())

    def test_symlink_zip_member_rejected(self):
        with zipfile.ZipFile(self.zip, "w") as archive:
            info = zipfile.ZipInfo("example_service/link")
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
            archive.writestr("example_service/new.txt", "new\n")
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

    def test_untrusted_zip_cannot_change_project_policy_or_runtime_state(self):
        stem = self.make_self_contained_zip()
        original = self.project_config.read_bytes()
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr(f"{self.root.name}/.apatch/config.yaml",
                             'schema_version: 1\nrequire_review_approval: false\n'
                             'require_required_checks: false\nchecks:\n  - ["true"]\n')
        result = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("protected apatch runtime path", result.stderr)
        self.assertEqual(self.project_config.read_bytes(), original)
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.state_path.exists())

    def test_zip_metadata_cannot_delete_project_policy_or_runtime_state(self):
        stem = self.make_self_contained_zip(override={"delete_paths": [".apatch/config.yaml"]})
        result = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("protected apatch runtime path", result.stderr)
        self.assertTrue(self.project_config.exists())
        self.assertFalse((self.root / "new.txt").exists())

    def test_zip_file_directory_prefix_conflict_aborts_before_extraction(self):
        stem = self.make_self_contained_zip()
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr(f"{self.root.name}/parent", "file\n")
            archive.writestr(f"{self.root.name}/parent/child.txt", "child\n")
        result = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Conflicting ZIP paths", result.stderr)
        self.assertFalse((self.root / "parent").exists())
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.state_path.exists())

    def test_git_fingerprint_includes_executable_bit_and_index_state(self):
        from apatch_lib.gitutil import worktree_fingerprint
        (self.root / "new.txt").write_text("new\n")
        first, _ = worktree_fingerprint(self.root)
        (self.root / "new.txt").chmod(0o755)
        executable, _ = worktree_fingerprint(self.root)
        self.assertNotEqual(first, executable)
        command("git", "add", "new.txt", cwd=self.root)
        staged, _ = worktree_fingerprint(self.root)
        self.assertNotEqual(executable, staged)

    def test_strict_commit_rejects_post_check_executable_change(self):
        stem = self.make_self_contained_zip()
        prepared = self.invoke_zip("--strict", "opSeq=APL,BRN,CHK", "skipApproves=true",
                                   selection=stem)
        self.assertEqual(prepared.returncode, 0, prepared.stderr + prepared.stdout)
        (self.root / "new.txt").chmod(0o755)
        denied = self.invoke_zip("--strict", "op=CMT", "skipApproves=true")
        self.assertEqual(denied.returncode, 2)
        self.assertIn("verified bytes", denied.stderr)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)

    def test_status_reads_legacy_record_without_cached_handoff(self):
        self.assertEqual(self.invoke_cli("op=BRN", "skipApproves=true").returncode, 0)
        self.assertEqual(self.invoke_cli("op=APL", "skipApproves=true").returncode, 0)
        self.assertFalse((self.root / ".apatch" / "params.json").exists())
        selected = self.invoke_zip("op=STS", f"patch={self.zip.name}")
        self.assertEqual(selected.returncode, 0, selected.stderr + selected.stdout)
        self.assertIn(f"Patch: {self.zip.name}", selected.stdout)
        unique = self.invoke_zip("op=STS")
        self.assertEqual(unique.returncode, 0, unique.stderr + unique.stdout)
        self.assertIn("PATCH STATUS 10 [STS]", unique.stdout)

    def test_repeated_successful_checks_are_not_reported_as_no_op(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("--strict", "opSeq=APL,BRN,CHK,CHK,STS",
                                 "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout.count("RESULT 4 [CHK]: SUCCESS"), 2)
        self.assertIn("SEQUENCE RESULT: SUCCESS", result.stdout)

    def test_canonical_check_timeout_stops_batch_and_preserves_commit(self):
        self.project_config.write_text('schema_version: 1\ncheck_timeout_seconds: 1\n'
                                       'checks:\n  - ["./run_checks.sh"]\n')
        command("git", "add", ".apatch/config.yaml", cwd=self.root)
        command("git", "commit", "-m", "Set canonical check timeout", cwd=self.root)
        command("git", "push", "origin", "main", cwd=self.root)
        current_head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.payload["base_commit"] = current_head
        stem = self.make_self_contained_zip()
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr(f"{self.root.name}/run_checks.sh", "#!/bin/sh\nsleep 30\n")
        started = time.monotonic()
        result = self.invoke_zip("opSeq=APL,BRN,CHK,CMT", "skipApproves=true", selection=stem)
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 2)
        self.assertIn("Canonical check timed out", result.stderr)
        self.assertIn("SEQUENCE STOP: 4 [CHK]", result.stdout)
        self.assertNotIn("SEQUENCE ACTION 5 [CMT]", result.stdout)
        self.assertLess(elapsed, 8)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), current_head)

    def test_invalid_project_check_timeout_is_rejected(self):
        for value in ("0", "3601", "true", "-1", "abc"):
            with self.subTest(value=value):
                self.project_config.write_text(
                    f'schema_version: 1\ncheck_timeout_seconds: {value}\n'
                    'checks:\n  - ["./run_checks.sh"]\n')
                result = self.invoke_zip("op=STS")
                self.assertEqual(result.returncode, 2)
                self.assertIn("check_timeout_seconds", result.stderr)
