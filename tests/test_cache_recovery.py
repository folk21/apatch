"""Recover legacy handoff caches without weakening verified ZIP identity checks."""

import hashlib
import json
import zipfile

from tests._support import LocalGitFixture, command


class CacheRecoveryTests(LocalGitFixture):
    def _legacy_cache(self, **changes):
        path = self.root / ".apatch" / "params.json"
        payload = {key: value for key, value in self.payload.items()
                   if key != "patch_sha256"}
        payload.update(changes)
        path.write_text(json.dumps(payload))
        return path

    def _cache_backups(self):
        return list((self.root / ".apatch" / "backups").glob("params-invalid-*.json"))

    def test_legacy_digest_cache_is_preserved_and_replaced_after_verified_apl(self):
        stem = self.make_self_contained_zip()
        cached = self._legacy_cache()
        old_bytes = cached.read_bytes()
        result = self.invoke_zip("opSeq=APL,BRN,CHK,STS", "skipApproves=true",
                                 selection=stem)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Invalid cached parameters preserved", result.stdout)
        self.assertIn("Canonical checks passed", result.stdout)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "feature/test-local-handoff")
        self.assertEqual(json.loads(cached.read_text())["patch_sha256"],
                         hashlib.sha256(self.zip.read_bytes()).hexdigest())
        backups = self._cache_backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old_bytes)

    def test_broken_cache_allows_checkpoint_only_sts_and_verified_brn_resume(self):
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        cached = self.root / ".apatch" / "params.json"
        cached.write_bytes(b"{broken")
        old_bytes = cached.read_bytes()
        history = self.history_path.read_bytes()
        state = self.state_path.read_bytes()
        status = self.invoke_zip("opSeq=STS")
        self.assertEqual(status.returncode, 0, status.stderr + status.stdout)
        self.assertIn("WARNING: Cached handoff unavailable", status.stdout)
        self.assertIn("Recorded phase: patch_applied", status.stdout)
        self.assertEqual(self.state_path.read_bytes(), state)
        self.assertEqual(cached.read_bytes(), old_bytes)
        resumed = self.invoke_zip("opSeq=BRN,CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        self.assertIn("Canonical checks passed", resumed.stdout)
        self.assertEqual(self.history_path.read_text().count("Patch: "), 1)
        self.assertIn(f"Patch: {self.zip.name}", self.history_path.read_text())
        self.assertNotEqual(self.history_path.read_bytes(), history)
        self.assertEqual([p.read_bytes() for p in self._cache_backups()], [old_bytes])
        self.assertEqual(json.loads(cached.read_text())["patch_file"], self.zip.name)

    def test_mismatched_repository_cache_is_backed_up_only_after_verified_selection(self):
        stem = self.make_self_contained_zip()
        cache = self._legacy_cache(repository="another_repository")
        old_bytes = cache.read_bytes()
        completed = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertEqual([p.read_bytes() for p in self._cache_backups()], [old_bytes])
        self.assertEqual(json.loads(cache.read_text())["repository"], self.root.name)

    def test_symlinked_cache_or_backups_rejects_apl_before_source_mutation(self):
        stem = self.make_self_contained_zip()
        cache = self.root / ".apatch" / "params.json"
        victim = self.base / "victim.txt"
        victim.write_text("unchanged\n")
        cache.symlink_to(victim)
        denied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(denied.returncode, 2)
        self.assertIn("Unsafe cached handoff path", denied.stderr)
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.state_path.exists())
        self.assertFalse((self.root / ".apatch" / "params.json.lock").exists())
        self.assertEqual(victim.read_text(), "unchanged\n")
        status = self.invoke_zip("op=STS")
        self.assertEqual(status.returncode, 2)
        self.assertIn("WARNING: Cached handoff unavailable", status.stdout)
        self.assertIn("No stored patch workflow matches", status.stderr)
        cache.unlink()
        self._legacy_cache()
        backups = self.root / ".apatch" / "backups"
        backups.symlink_to(self.base)
        denied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(denied.returncode, 2)
        self.assertIn("Unsafe cached handoff backup directory", denied.stderr)
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.state_path.exists())

    def test_oversized_cache_rejects_new_apl_without_extracting(self):
        stem = self.make_self_contained_zip()
        cache = self.root / ".apatch" / "params.json"
        cache.write_bytes(b"x" * 65537)
        denied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(denied.returncode, 2)
        self.assertIn("Cached parameters exceed 64 KiB", denied.stderr)
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.state_path.exists())
        self.assertFalse((self.root / ".apatch" / "params.json.lock").exists())
        self.assertEqual(cache.stat().st_size, 65537)

    def test_unverified_resume_does_not_replace_legacy_cache(self):
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        cache = self._legacy_cache()
        old_bytes = cache.read_bytes()
        state = json.loads(self.state_path.read_text())
        state["operation_runs"] = [run for run in state["operation_runs"]
                                   if run["operation"]["number"] != 3]
        self.state_path.write_text(json.dumps(state))
        denied = self.invoke_zip("opSeq=BRN,CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(denied.returncode, 2)
        self.assertIn("matching successful APL journal run is missing", denied.stderr)
        self.assertEqual(cache.read_bytes(), old_bytes)
        self.assertEqual(self._cache_backups(), [])
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
                         "main")

    def test_tampered_zip_does_not_repair_invalid_cache(self):
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        cache = self._legacy_cache()
        previous = cache.read_bytes()
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr("example_service/tampered.txt", "tampered\n")
        denied = self.invoke_zip("opSeq=BRN,CHK,STS", "skipApproves=true", selection=stem)
        self.assertEqual(denied.returncode, 2)
        self.assertIn("Selected ZIP identity or digest conflicts", denied.stderr)
        self.assertEqual(cache.read_bytes(), previous)
        self.assertEqual(self._cache_backups(), [])
        self.assertFalse((self.root / "tampered.txt").exists())

