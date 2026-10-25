"""Regression tests for the handoffs subsystem."""

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


class HandoffsTests(LocalGitFixture):
    def test_self_contained_lifecycle_loose(self):
        self.assert_self_contained_lifecycle("loose")

    def test_self_contained_lifecycle_strict(self):
        self.assert_self_contained_lifecycle("strict")

    def test_self_contained_lifecycle_force(self):
        self.assert_self_contained_lifecycle("force")

    def test_self_contained_zip_sequence_and_deprecated_bap(self):
        stem = self.make_self_contained_zip()
        forbidden = self.invoke_zip("op=BAP", "skipApproves=true", selection=stem)
        self.assertEqual(forbidden.returncode, 2)
        self.assertIn("deprecated", forbidden.stderr)
        combined = self.invoke_zip("--strict", "opSeq=APL,BRN,CHK", "skipApproves=true", selection=stem)
        self.assertEqual(combined.returncode, 0, combined.stderr + combined.stdout)
        self.assertIn("SEQUENCE", combined.stdout)
        self.assertIn("Next suggested: 5 [CMT]", combined.stdout)
        stale_bap = self.invoke_zip("op=2", "skipApproves=true")
        self.assertEqual(stale_bap.returncode, 2)
        self.assertIn("deprecated", stale_bap.stderr)

    def test_multi_zip_sequence_combines_patches_and_final_status(self):
        first = self.make_self_contained_zip()
        second = self.make_followup_zip()
        result = self.invoke_zip("opSeq=APL,BRN,APL,CHK,CMT,STS",
                                 f"handoffSeq={first},{second.stem}", "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout.count("SEQUENCE ACTION 3 [APL]"), 2)
        self.assertIn(f"Selected ZIP: {self.zip.name}", result.stdout)
        self.assertIn(f"Selected ZIP: {second.name}", result.stdout)
        self.assertIn("Backed up 1 overlapping file", result.stdout)
        self.assertIn("PATCH STATUS 10 [STS]", result.stdout)
        self.assertIn(f"Patch: {second.name}", result.stdout)
        self.assertIn("SEQUENCE RESULT: SUCCESS", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])
        self.assertEqual((self.root / "existing.txt").read_text(), "second revision\n")
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")
        self.assertEqual((self.root / "second.txt").read_text(), "second patch\n")
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 2)
        workflows = json.loads(self.state_path.read_text())["workflows"]
        self.assertEqual(len(workflows), 2)
        self.assertTrue(all(record["phase"] == "committed" for record in workflows.values()))
        self.assertEqual(json.loads((self.root / ".apatch" / "params.json").read_text())["patch_file"],
                         second.name)
        changed = command("git", "show", "--pretty=", "--name-only", "HEAD", cwd=self.root).stdout.splitlines()
        self.assertEqual(set(changed), {"existing.txt", "new.txt", "second.txt"})

    def test_explicit_followup_zip_after_previous_invocation_combines_uncommitted_changes(self):
        first = self.make_self_contained_zip()
        initial = self.invoke_zip("opSeq=APL,BRN", "skipApproves=true", selection=first)
        self.assertEqual(initial.returncode, 0, initial.stderr + initial.stdout)
        original_workflows = json.loads(self.state_path.read_text())["workflows"]
        second = self.make_followup_zip()

        implicit = self.invoke_zip("op=APL", "skipApproves=true", selection=second.stem)
        self.assertEqual(implicit.returncode, 2)
        self.assertIn("followup=true", implicit.stderr)
        self.assertEqual(json.loads(self.state_path.read_text())["workflows"], original_workflows)
        self.assertFalse((self.root / "second.txt").exists())

        repaired = self.invoke_zip("followup=true", "opSeq=APL,CHK,CMT,STS",
                                   "skipApproves=true", selection=second.stem)
        self.assertEqual(repaired.returncode, 0, repaired.stderr + repaired.stdout)
        self.assertIn("Backed up 1 overlapping file", repaired.stdout)
        backups = list((self.root / ".apatch/backups").glob("overlap-*/existing.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "updated\n")
        self.assertIn("PATCH STATUS 10 [STS]", repaired.stdout)
        self.assertEqual((self.root / "existing.txt").read_text(), "second revision\n")
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")
        self.assertEqual((self.root / "second.txt").read_text(), "second patch\n")
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        self.assertEqual(len(AppliedPatchHistory(self.history_path).entries), 2)
        workflows = json.loads(self.state_path.read_text())["workflows"]
        self.assertEqual(len(workflows), 2)
        self.assertEqual({item["phase"] for item in workflows.values()}, {"committed"})
        self.assertEqual(len({item["commit_sha"] for item in workflows.values()}), 1)
        self.assertEqual(json.loads((self.root / ".apatch/params.json").read_text())["patch_file"],
                         second.name)

    def test_followup_requires_matching_pending_branch_and_rejects_mode_conflicts(self):
        first = self.make_self_contained_zip()
        second = self.make_followup_zip()
        invalid = (
            ("followup=true", "op=APL", "skipApproves=true"),
            ("followup=true", "op=CHK", "skipApproves=true"),
            ("followup=true", "--strict", "op=APL", "skipApproves=true"),
            ("followup=true", "--force", "op=APL", "skipApproves=true"),
            ("followup=true", "opSeq=APL,BRN,APL", f"handoffSeq={first},{second.stem}",
             "skipApproves=true"),
        )
        for options in invalid:
            with self.subTest(options=options):
                denied = self.invoke_zip(*options, selection=second.stem)
                self.assertEqual(denied.returncode, 2, denied.stderr + denied.stdout)
                self.assertFalse((self.root / "second.txt").exists())
        prior = json.loads(self.state_path.read_text())
        self.assertEqual(prior["workflows"], {})
        self.assertEqual([run["outcome"] for run in prior["operation_runs"]], ["FAILED"])

        self.assertEqual(self.invoke_zip("opSeq=APL,BRN", "skipApproves=true",
                                         selection=first).returncode, 0)
        unchanged = json.loads(self.state_path.read_text())["workflows"]
        mismatched = self.make_followup_zip(filename="example_service-PATCH-wrong-branch.zip",
                                            override={"feature_branch": "feature/other"})
        denied = self.invoke_zip("followup=true", "op=APL", "skipApproves=true",
                                 selection=mismatched.stem)
        self.assertEqual(denied.returncode, 2, denied.stderr + denied.stdout)
        self.assertIn("targets feature/other", denied.stderr)
        self.assertFalse((self.root / "second.txt").exists())
        self.assertEqual(json.loads(self.state_path.read_text())["workflows"], unchanged)

    def test_followup_refuses_dirty_feature_branch_without_an_applied_predecessor(self):
        second = self.make_followup_zip()
        command("git", "switch", "-c", self.payload["feature_branch"], cwd=self.root)
        (self.root / "manual.txt").write_text("user-owned change\n")
        denied = self.invoke_zip("followup=true", "op=APL", "skipApproves=true",
                                 selection=second.stem)
        self.assertEqual(denied.returncode, 2, denied.stderr + denied.stdout)
        self.assertIn("matching unfinished, uncommitted ZIP workflow", denied.stderr)
        self.assertEqual((self.root / "manual.txt").read_text(), "user-owned change\n")
        self.assertFalse((self.root / "second.txt").exists())
        self.assertEqual(json.loads(self.state_path.read_text())["workflows"], {})

    def test_multi_zip_shell_launcher_accepts_download_paths_and_pushes_combined_commit(self):
        first = self.make_self_contained_zip()
        second = self.make_followup_zip()
        self.prepare_test_launcher()
        result = subprocess.run(
            ["sh", str(self.bin / "apatch.sh"), first,
             "opSeq=APL,BRN,APL,CHK,CMT,PSH,STS",
             f"handoffSeq={self.zip},{second}", "skipApproves=true"],
            cwd=self.root, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("SEQUENCE ACTION 10 [STS]", result.stdout)
        self.assertNotIn("step 7/7", result.stdout.lower())
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, "")
        commit = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        remote = command("git", "ls-remote", "--heads", "origin",
                         "refs/heads/feature/test-local-handoff", cwd=self.root).stdout.split()[0]
        self.assertEqual(commit, remote)
        records = json.loads(self.state_path.read_text())["workflows"]
        self.assertEqual(len(records), 2)
        self.assertEqual({record.get("pushed_sha") for record in records.values()}, {commit})

    def test_single_explicit_handoff_sequence_matches_normal_zip_workflow(self):
        first = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN,CHK", f"handoffSeq={first}",
                                 "skipApproves=true")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("SEQUENCE RESULT: SUCCESS", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         self.payload["feature_branch"])

    def test_multi_zip_preflight_rejects_inconsistent_inputs_without_side_effects(self):
        first = self.make_self_contained_zip()
        second = self.make_followup_zip()
        valid = f"handoffSeq={first},{second.stem}"
        invalid = (
            ("opSeq=APL,BRN,APL,CHK", f"handoffSeq={first}"),
            ("opSeq=APL,BRN,APL,CHK", f"handoffSeq={first},{first}"),
            ("opSeq=APL,APL,BRN,CHK", valid),
            ("opSeq=APL,BRN,APL,CMT,CHK", f"handoffSeq={first},missing"),
            ("opSeq=APL,BRN,APL", f"handoffSeq={first},../{second.name}"),
            ("opSeq=APL,BRN,APL", valid, "--strict"),
            ("opSeq=APL,BRN,APL", valid, "--force"),
            ("opSeq=APL,BRN,APL,CMT,APL", valid),
            ("opSeq=APL", f"handoffSeq={first},{second.stem}"),
            ("op=APL", valid),
            ("opSeq=APL,BRN,APL", valid, self.zip.stem + "-wrong"),
            ("opSeq=APL,BRN,APL", f"handoffSeq={first},{self.base / second.name}"),
        )
        for options in invalid:
            with self.subTest(options=options):
                result = self.invoke_zip(*options, "skipApproves=true")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse((self.root / "new.txt").exists())
                self.assertFalse(self.state_path.exists())
                self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                                 "main")
        branch_mismatch = self.make_followup_zip(override={"feature_branch": "feature/other"})
        failed = self.invoke_zip("opSeq=APL,BRN,APL", valid, "skipApproves=true")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("same feature branch", failed.stderr)
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.state_path.exists())

    def test_multi_zip_check_failure_stops_before_commit_and_keeps_second_cache(self):
        first = self.make_self_contained_zip()
        second = self.make_followup_zip(extra_files={"run_checks.sh": "#!/bin/sh\nexit 1\n"})
        result = self.invoke_zip("opSeq=APL,BRN,APL,CHK,CMT",
                                 f"handoffSeq={first},{second.stem}", "skipApproves=true")
        self.assertEqual(result.returncode, 2)
        self.assertIn("SEQUENCE STOP: 4 [CHK]", result.stdout)
        self.assertNotIn("SEQUENCE ACTION 5 [CMT]", result.stdout)
        self.assertEqual((self.root / "second.txt").read_text(), "second patch\n")
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(), self.head)
        self.assertEqual(json.loads((self.root / ".apatch" / "params.json").read_text())["patch_file"],
                         second.name)

    def test_self_contained_zip_invalid_metadata_does_not_extract_or_cache(self):
        for variant in ({"repository": "elsewhere"}, {"patch_sha256": "0" * 64},
                        {"feature_branch": "main"}):
            with self.subTest(variant=variant):
                stem = self.make_self_contained_zip(override=variant)
                result = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
                self.assertEqual(result.returncode, 2)
                self.assertFalse((self.root / "new.txt").exists())
                self.assertFalse((self.root / ".apatch" / "params.json").exists())
        stem = self.make_self_contained_zip(include_metadata=False)
        result = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 2)
        self.assertIn("exactly one", result.stderr)

    def test_cached_self_contained_parameters_reject_corruption_and_symlink(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        cached_path = self.root / ".apatch" / "params.json"
        cached_path.write_text("{invalid")
        failed = self.invoke_zip("op=BRN", "skipApproves=true")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("Cannot read .apatch/params.json", failed.stderr)
        cached_path.unlink()
        cached_path.symlink_to(self.params)
        failed = self.invoke_zip("op=BRN", "skipApproves=true")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("Unsafe cached handoff path", failed.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(), "main")

    def test_zip_selected_can_recover_missing_cache_after_successful_apl(self):
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        cache = self.root / ".apatch" / "params.json"
        cache.unlink()
        unavailable = self.invoke_zip("op=BRN", "skipApproves=true")
        self.assertEqual(unavailable.returncode, 2)
        recovered = self.invoke_zip("op=BRN", "skipApproves=true", selection=stem)
        self.assertEqual(recovered.returncode, 0, recovered.stderr + recovered.stdout)
        self.assertTrue(cache.is_file())
        self.assertEqual(self.invoke_zip("op=CHK").returncode, 0)

    def test_zip_branch_can_recover_a_manually_completed_switch(self):
        stem = self.make_self_contained_zip()
        self.assertEqual(self.invoke_zip("op=APL", "skipApproves=true", selection=stem).returncode, 0)
        command("git", "switch", "-c", "feature/test-local-handoff", cwd=self.root)
        recovered = self.invoke_zip("op=BRN", "skipApproves=true")
        self.assertEqual(recovered.returncode, 0, recovered.stderr + recovered.stdout)
        self.assertIn("Recovering a previously switched feature branch", recovered.stdout)
        self.assertEqual(self.invoke_zip("op=CHK").returncode, 0)

    def test_embedded_metadata_must_be_unique_regular_and_repository_scoped(self):
        stem = self.make_self_contained_zip()
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr(f"{self.root.name}/.apatch/params.json", "{}")
        duplicate = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("exactly one", duplicate.stderr)
        stem = self.make_self_contained_zip()
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr(f"{self.root.name}/existing.txt", "updated\n")
            metadata = zipfile.ZipInfo(f"{self.root.name}/.apatch/params.json")
            metadata.create_system = 3
            metadata.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(metadata, "dangerous-target")
        linked = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(linked.returncode, 2)
        self.assertIn("regular JSON", linked.stderr)
        self.assertFalse((self.root / "new.txt").exists())

    def test_missing_cached_handoff_requires_explicit_zip_or_json(self):
        self.prepare_test_launcher()
        cases = (
            ["sh", str(self.bin / "apatch.sh")],
            ["sh", str(self.bin / "apatch.sh"), "force"],
            ["sh", str(self.bin / "apatch.sh"), "--force"],
            [sys.executable, str(self.bin / "apatch.py")],
            [sys.executable, str(self.bin / "apatch.py"), "--force"],
        )
        before = command("git", "status", "--porcelain", cwd=self.root).stdout
        for argv in cases:
            with self.subTest(argv=argv):
                result = subprocess.run(argv, cwd=self.root,
                                        input="0\n", capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn(".apatch/params.json", result.stderr)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout, before)
        self.assertFalse(self.state_path.exists())

    def test_named_handoffs_select_distinct_json_files_under_configured_downloads(self):
        first = self.params.stem
        second = "example_service-PATCH-2026-10-24-01-00-second"
        second_json = self.params.with_name(second + ".json")
        second_payload = dict(self.payload, patch_file="another-patch.zip")
        second_json.write_text(json.dumps(second_payload))
        for identifier, patch_name in ((first, self.zip.name), (first + ".json", self.zip.name),
                                       (second, "another-patch.zip"), (second + ".json", "another-patch.zip")):
            with self.subTest(identifier=identifier):
                result = subprocess.run([sys.executable, str(self.bin / "apatch.py"), identifier, "op=STS"],
                                        cwd=self.root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"Patch: {patch_name}", result.stdout)
        self.assertFalse(self.state_path.exists())

    def test_explicit_relative_stem_and_json_path_still_work(self):
        relative_json = self.root / "relative-handoff.json"
        shutil.copy2(self.params, relative_json)
        for identifier in ("./relative-handoff", "./relative-handoff.json", str(self.params)):
            with self.subTest(identifier=identifier):
                result = subprocess.run([sys.executable, str(self.bin / "apatch.py"), identifier, "op=STS"],
                                        cwd=self.root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"Patch: {self.zip.name}", result.stdout)

    def test_malformed_or_unknown_handoff_stem_fails_before_workflow_mutation(self):
        for name in ("", "..", "missing-handoff", "evil:name"):
            with self.subTest(name=name):
                result = subprocess.run([sys.executable, str(self.bin / "apatch.py"), name, "op=APL"],
                                        cwd=self.root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.state_path.exists())
                self.assertFalse(self.history_path.exists())
