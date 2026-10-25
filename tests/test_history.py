"""Regression tests for the history subsystem."""

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


class HistoryTests(LocalGitFixture):
    def test_legacy_state_and_history_migrate_without_deleting_originals(self):
        applied = self.invoke("2\nYES\nYES\n")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        old_state = self.bin / self.state_path.name
        old_history = self.bin / self.history_path.name
        original_state = json.loads(self.state_path.read_text())
        original_state["workflows"]["foreign-project"] = {"repository": str(self.base / "another-repo")}
        old_state.write_text(json.dumps(original_state))
        old_history.write_bytes(self.history_path.read_bytes())
        self.state_path.unlink()
        self.history_path.unlink()

        verified = self.invoke("4\n")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("Imported 1 workflow checkpoint(s)", verified.stdout)
        self.assertIn("Imported 1 applied-patch history", verified.stdout)
        migrated = json.loads(self.state_path.read_text())
        self.assertEqual(len(migrated["workflows"]), 1)
        self.assertEqual(next(iter(migrated["workflows"].values()))["phase"], "verified")
        self.assertEqual(self.history_path.read_text(), old_history.read_text())
        self.assertTrue(old_state.exists())
        self.assertTrue(old_history.exists())
        self.assertTrue(self.lock_path.exists())
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         " M existing.txt\n?? new.txt\n")

    def test_prefixed_project_local_state_and_history_migrate_without_deletion(self):
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        old_state = self.state_path.with_name(f"{self.root.name}_apply_patch.state.json")
        old_history = self.history_path.with_name(f"{self.root.name}_applied_patches.txt")
        shutil.copy2(self.state_path, old_state)
        shutil.copy2(self.history_path, old_history)
        self.state_path.unlink()
        self.history_path.unlink()

        result = self.invoke("4\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Imported 1 workflow checkpoint(s)", result.stdout)
        self.assertIn("Imported 1 applied-patch history", result.stdout)
        migrated = json.loads(self.state_path.read_text())
        previous = json.loads(old_state.read_text())
        self.assertEqual(migrated["workflows"].keys(), previous["workflows"].keys())
        self.assertEqual(next(iter(migrated["workflows"].values()))["phase"], "verified")
        self.assertEqual(next(iter(previous["workflows"].values()))["phase"], "patch_applied")
        self.assertEqual(self.history_path.read_bytes(), old_history.read_bytes())
        self.assertTrue(old_state.exists())
        self.assertTrue(old_history.exists())

    def test_prefixed_legacy_one_line_history_migrates_and_remains_readable(self):
        old_history = self.history_path.with_name(f"{self.root.name}_applied_patches.txt")
        old_history.write_text(self.zip.name + "\n")
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.history_path.read_text(), old_history.read_text())
        entries = AppliedPatchHistory(self.history_path).entries
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0].date)

    def test_structured_history_tracks_distinct_patches_and_dates(self):
        from apatch_lib.patch_history import locked_history
        with locked_history(self.history_path) as history:
            self.assertTrue(history.append(self.zip.name, "feature/planned", "main"))
            self.assertTrue(history.append("another-change.zip", "feature/other", "release/one"))
            self.assertFalse(history.append(self.zip.name, "feature/planned", "main"))
        entries = AppliedPatchHistory(self.history_path).entries
        self.assertEqual(len(entries), 2)
        self.assertEqual([entry.real_branch for entry in entries], ["main", "release/one"])
        self.assertEqual(self.history_path.read_text().count("Date: "), 2)
        self.assertIn("\n\nDate: ", self.history_path.read_text())

    def test_malformed_structured_history_blocks_patch(self):
        self.history_path.write_text(
            "Date: not-a-date\nPatch: good.zip\n"
            "Planned feature branch: feature/foo\nReal feature branch: main\n")
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("history contains an invalid date", result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "main")

    def test_force_commit_updates_legacy_history_into_structured_entry(self):
        (self.root / "existing.txt").write_text("updated\n")
        (self.root / "new.txt").write_text("new\n")
        self.history_path.write_text(self.zip.name + "\n")
        result = self.invoke_force("5\nYES\nYES\nYES\nYES\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_history(real_branch="main")

    def test_existing_project_state_is_not_replaced_by_legacy_state(self):
        self.assertEqual(self.invoke("2\nYES\nYES\n").returncode, 0)
        original = self.state_path.read_bytes()
        old_state = self.bin / self.state_path.name
        old_state.write_text(json.dumps({"schema_version": 1, "workflows": {"foreign": {
            "repository": str(self.base / "another-repo")}}}))
        result = self.invoke("0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state_path.read_bytes(), original)

    def test_previously_applied_patch_warns_and_requires_yes_no(self):
        history = self.history_path
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
        history = self.history_path
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

    def test_corrupt_patch_history_rejects_without_branch_creation(self):
        history = self.history_path
        history.write_text("invalid/entry.zip\n")
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("history contains an invalid entry", result.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")

    def test_missing_created_predecessor_blocks_bap_and_apl_in_all_modes(self):
        self.write_created_registry("first-generated.zip", self.zip.name, "later-generated.zip")
        for mode in ("loose", "strict", "force"):
            for operation in ("BAP", "APL"):
                with self.subTest(mode=mode, operation=operation):
                    result = self.invoke_cli(f"--{mode}", f"op={operation}",
                                             "skipApproves=true")
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("[PATCH_ORDER] Patch first-generated.zip has not been applied!",
                                  result.stderr)
                    self.assertIn(f"Cannot apply {self.zip.name}", result.stderr)
                    self.assertEqual(command("git", "branch", "--show-current", cwd=self.root)
                                     .stdout.strip(), "main")
                    self.assertFalse(command("git", "branch", "--list",
                                             self.payload["feature_branch"], cwd=self.root)
                                     .stdout.strip())
                    self.assertFalse((self.root / "new.txt").exists())
                    self.assertFalse(self.history_path.exists())

    def test_registered_patch_after_applied_legacy_predecessor_can_be_applied(self):
        self.write_created_registry("earlier-patch.zip", self.zip.name, "future-patch.zip")
        self.history_path.write_text("earlier-patch.zip\n")
        result = self.invoke_cli("--loose", "op=BAP", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([entry.patch for entry in AppliedPatchHistory(self.history_path).entries],
                         ["earlier-patch.zip", self.zip.name])
        self.assertTrue((self.root / "new.txt").exists())

    def test_registered_first_patch_is_not_blocked_by_later_unapplied_patches(self):
        self.write_created_registry(self.zip.name, "later-a.zip", "later-b.zip")
        result = self.invoke_cli("--strict", "op=BAP", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_history(real_branch=self.payload["feature_branch"])

    def test_force_applies_registry_patch_after_structured_predecessor(self):
        from apatch_lib.patch_history import locked_history
        self.write_created_registry("earlier-patch.zip", self.zip.name)
        with locked_history(self.history_path) as history:
            history.append("earlier-patch.zip", "feature/prior", "main")
        result = self.invoke_cli("--force", "op=BAP", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 2)
        self.assertTrue((self.root / "new.txt").exists())

    def test_unregistered_patch_is_rejected_in_every_mode(self):
        registry = self.write_created_registry("another-generated.zip")
        for mode in ("loose", "strict", "force"):
            with self.subTest(mode=mode):
                result = self.invoke_cli(f"--{mode}", "op=BAP", "skipApproves=true")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(f"Patch {self.zip.name} is not registered", result.stderr)
                self.assertIn(str(registry), result.stderr)
                self.assertEqual(command("git", "branch", "--show-current", cwd=self.root)
                                 .stdout.strip(), "main")

    def test_invalid_registry_lines_and_duplicates_reject_before_branch_mutation(self):
        invalid_lists = (
            ("blank", self.zip.name + "\n\n"),
            ("traversal", "../other.zip\n" + self.zip.name + "\n"),
            ("absolute", "/tmp/other.zip\n" + self.zip.name + "\n"),
            ("comment", "# comment\n" + self.zip.name + "\n"),
            ("json", "some.json\n" + self.zip.name + "\n"),
            ("duplicate", self.zip.name + "\n" + self.zip.name + "\n"),
        )
        path = self.root / ".apatch" / "created_patches.txt"
        for label, content in invalid_lists:
            with self.subTest(label=label):
                path.write_text(content)
                result = self.invoke_cli("--loose", "op=BAP", "skipApproves=true")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("[PATCH_ORDER]", result.stderr)
                self.assertIn("line", result.stderr)
                self.assertEqual(command("git", "branch", "--show-current", cwd=self.root)
                                 .stdout.strip(), "main")
                self.assertFalse((self.root / "new.txt").exists())

    def test_registry_symlink_and_invalid_utf8_are_rejected(self):
        registry = self.root / ".apatch" / "created_patches.txt"
        outside = self.base / "external-registry.txt"
        outside.write_text(self.zip.name + "\n")
        registry.symlink_to(outside)
        result = self.invoke_cli("--force", "op=BAP", "skipApproves=true")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("must not be a symlink", result.stderr)
        self.assertEqual(outside.read_text(), self.zip.name + "\n")
        registry.unlink()
        registry.write_bytes(b"\xff.zip\n")
        invalid = self.invoke_cli("--loose", "op=APL", "skipApproves=true")
        self.assertEqual(invalid.returncode, 2, invalid.stdout + invalid.stderr)
        self.assertIn("Cannot read UTF-8", invalid.stderr)
        self.assertFalse((self.root / "new.txt").exists())

    def test_order_guard_runs_before_superseding_unfinished_state(self):
        self.write_created_registry("unapplied-old.zip", self.zip.name)
        original = {"schema_version": 1, "workflows": {"older": {
            "repository": str(self.root.resolve()), "patch_file": "older.zip",
            "branch": "feature/previous", "phase": "patch_applied"}}}
        contents = json.dumps(original)
        self.state_path.write_text(contents)
        blocked = self.invoke_cli("--loose", "op=APL", "skipApproves=true")
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("unapplied-old.zip has not been applied!", blocked.stderr)
        self.assertEqual(self.state_path.read_text(), contents)

    def test_missing_registry_retains_previous_apply_behavior(self):
        self.assertFalse((self.root / ".apatch" / "created_patches.txt").exists())
        result = self.invoke_cli("--loose", "op=APL", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_history(real_branch="main")

    def test_created_registry_is_excluded_locally_without_tracking(self):
        registry = self.write_created_registry(self.zip.name)
        result = self.invoke_cli("--loose", "op=EXT")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(command("git", "check-ignore", ".apatch/created_patches.txt",
                                 cwd=self.root).stdout.strip(), ".apatch/created_patches.txt")
        self.assertNotIn("created_patches.txt", command("git", "status", "--porcelain",
                                                          cwd=self.root).stdout)
        self.assertEqual(registry.read_text(), self.zip.name + "\n")

    def test_zip_registry_metadata_bootstraps_in_loose(self):
        self.assert_registry_metadata_bootstrap("loose")

    def test_zip_registry_metadata_bootstraps_in_strict(self):
        self.assert_registry_metadata_bootstrap("strict")

    def test_zip_registry_metadata_bootstraps_in_force(self):
        self.assert_registry_metadata_bootstrap("force")

    def test_zip_registry_metadata_extends_existing_prefix(self):
        old = "earlier-generated.zip"
        self.write_created_registry(old)
        self.history_path.write_text(old + "\n")
        self.add_registry_member(old + "\n" + self.zip.name + "\n")
        result = self.invoke_cli("--loose", "op=BAP", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / ".apatch" / "created_patches.txt").read_text(),
                         old + "\n" + self.zip.name + "\n")
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 2)

    def test_zip_registry_metadata_rejects_missing_predecessors_before_branch(self):
        self.add_registry_member("missing-first.zip\n" + self.zip.name + "\n")
        for mode in ("loose", "strict", "force"):
            with self.subTest(mode=mode):
                result = self.invoke_cli(f"--{mode}", "op=BAP", "skipApproves=true")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("missing-first.zip has not been applied!", result.stderr)
                self.assertFalse((self.root / ".apatch" / "created_patches.txt").exists())
                self.assertFalse((self.root / "new.txt").exists())
                self.assertEqual(command("git", "branch", "--show-current", cwd=self.root)
                                 .stdout.strip(), "main")

    def test_zip_registry_metadata_prefix_conflict_preserves_original_bytes(self):
        path = self.write_created_registry("first.zip", "second.zip")
        original = path.read_bytes()
        self.add_registry_member("first.zip\n" + self.zip.name + "\n")
        denied = self.invoke_cli("--loose", "op=BAP", "skipApproves=true")
        self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
        self.assertIn("does not extend the existing prefix", denied.stderr)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / "new.txt").exists())

    def test_zip_registry_metadata_rejects_corruption_and_duplicate_members(self):
        self.add_registry_member(self.zip.name + "\n" + self.zip.name + "\n")
        denied = self.invoke_cli("--strict", "op=BAP", "skipApproves=true")
        self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
        self.assertIn("Duplicate created patch", denied.stderr)

    def test_zip_registry_metadata_rejects_invalid_utf8(self):
        self.add_registry_member(b"\xff\xfe")
        denied = self.invoke_cli("--loose", "op=BAP", "skipApproves=true")
        self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
        self.assertIn("Cannot read UTF-8 created-patch registry", denied.stderr)
        self.assertFalse((self.root / "new.txt").exists())

    def test_zip_registry_metadata_rejects_symlink_member(self):
        member = zipfile.ZipInfo(f"{self.root.name}/.apatch/created_patches.txt")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr(member, "target")
        self.payload["patch_sha256"] = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))
        denied = self.invoke_cli("--force", "op=BAP", "skipApproves=true")
        self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
        self.assertIn("Unsupported ZIP file type", denied.stderr)
        self.assertFalse((self.root / "new.txt").exists())

    def test_registry_persistence_is_idempotent(self):
        from apatch_lib.created_patches import persist_registry
        self.write_created_registry(self.zip.name)
        registry = self.root / ".apatch" / "created_patches.txt"
        original = registry.stat()
        self.assertFalse(persist_registry(self.root, (self.zip.name,)))
        after = registry.stat()
        self.assertEqual(after.st_ino, original.st_ino)
        self.assertEqual(after.st_mtime_ns, original.st_mtime_ns)

    def test_zip_registry_metadata_rejects_duplicate_archive_members(self):
        self.add_registry_member(self.zip.name + "\n")
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr(f"{self.root.name}/.apatch/created_patches.txt", self.zip.name + "\n")
        self.payload["patch_sha256"] = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.params.write_text(json.dumps(self.payload))
        denied = self.invoke_cli("--strict", "op=BAP", "skipApproves=true")
        self.assertEqual(denied.returncode, 2, denied.stdout + denied.stderr)
        self.assertIn("Duplicate/conflicting created-patch metadata", denied.stderr)
        self.assertFalse((self.root / "new.txt").exists())

    def test_registry_persist_failure_after_extraction_is_recoverable(self):
        from apatch_lib.gitutil import set_skip_approvals, reset_skip_approvals
        from apatch_lib.workflow import Workflow
        self.add_registry_member(self.zip.name + "\n")
        config = load_project_config(self.root, load_config(self.bin))
        handoff = load_handoff(self.params)
        workflow = Workflow(self.root, config, handoff,
                            {"schema_version": 1, "workflows": {}}, loose=True)
        token = set_skip_approvals(True)
        try:
            with patch("apatch_lib.loose.persist_registry", side_effect=Abort("simulated registry I/O failure")):
                with self.assertRaisesRegex(Abort, "simulated registry I/O failure"):
                    workflow.loose_actions.apply_patch()
        finally:
            reset_skip_approvals(token)
        self.assertTrue((self.root / "new.txt").exists())
        self.assertFalse((self.root / ".apatch" / "created_patches.txt").exists())
        self.assertFalse(self.history_path.exists())
        saved = json.loads(self.state_path.read_text())
        self.assertEqual(saved["workflows"][workflow.key]["phase"], "applying")
        recovered = self.invoke_cli("--force", "op=APL", "skipApproves=true")
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertEqual((self.root / ".apatch" / "created_patches.txt").read_text(),
                         self.zip.name + "\n")
        self.assert_history(real_branch="main")

    def test_misspelled_history_field_blocks_every_branch_action_before_switch(self):
        original = (
            "Date: 2026-10-23T22:50:10+04:00\n"
            "Patch: previous-patch.zip\n"
            "Planned feature brancx§h: feature/previous\n"
            "Real feature branch: feature/previous\n")
        self.history_path.write_text(original)
        for mode in ("loose", "strict", "force"):
            for operation in ("BRN", "BAP"):
                with self.subTest(mode=mode, operation=operation):
                    result = self.invoke_cli(f"--{mode}", f"op={operation}",
                                             "skipApproves=true")
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("invalid entry at line 3", result.stderr)
                    self.assertIn("expected 'Planned feature branch:'", result.stderr)
                    self.assertIn("found 'Planned feature brancx§h'", result.stderr)
                    self.assertEqual(command("git", "branch", "--show-current", cwd=self.root)
                                     .stdout.strip(), "main")
                    self.assertFalse(command("git", "branch", "--list",
                                             self.payload["feature_branch"], cwd=self.root)
                                     .stdout.strip())
                    self.assertFalse((self.root / "new.txt").exists())
                    self.assertEqual(self.history_path.read_text(), original)

        self.history_path.write_text(original.replace("brancx§h", "branch"))
        recovered = self.invoke_cli("--loose", "op=BAP", "skipApproves=true")
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertTrue((self.root / "new.txt").exists())
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 2)

    def test_misspelled_history_field_prevents_switch_to_existing_branch(self):
        command("git", "branch", self.payload["feature_branch"], cwd=self.root)
        history = ("Date: 2026-10-23T22:50:10+04:00\n"
                   "Patch: previous-patch.zip\n"
                   "Planned feature brancx§h: feature/previous\n"
                   "Real feature branch: feature/previous\n")
        self.history_path.write_text(history)
        for mode in ("loose", "force"):
            with self.subTest(mode=mode):
                result = self.invoke_cli(f"--{mode}", "op=BAP", "skipApproves=true")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("invalid entry at line 3", result.stderr)
                self.assertEqual(command("git", "branch", "--show-current", cwd=self.root)
                                 .stdout.strip(), "main")
                self.assertFalse((self.root / "new.txt").exists())
                self.assertEqual(self.history_path.read_text(), history)

    def test_symlink_patch_history_is_rejected(self):
        protected = self.base / "protected.txt"
        protected.write_text("original")
        self.history_path.symlink_to(protected)
        result = self.invoke("2\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Runtime state and history files must not be symlinks", result.stderr)
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
        state = json.loads(self.state_path.read_text())
        self.assertEqual(next(iter(state["workflows"].values()))["phase"], "committed")

    def test_history_lock_rejects_concurrent_use(self):
        from apatch_lib.patch_history import locked_history
        path = self.history_path
        with locked_history(path) as history:
            self.assertFalse(history.contains(self.zip.name))
            with self.assertRaises(Abort):
                with locked_history(path):
                    pass
            history.append(self.zip.name, self.payload["feature_branch"], "main")
        with locked_history(path) as history:
            self.assertTrue(history.contains(self.zip.name))
            history.append(self.zip.name, self.payload["feature_branch"], "main")
        self.assert_history(real_branch="main")
