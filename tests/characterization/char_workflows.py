"""Opt-in cross-subsystem Git/ZIP behavior baselines for architecture changes."""

import hashlib
import json
import zipfile

from tests._support import LocalGitFixture, command


class PublicWorkflowCharacterizationTests(LocalGitFixture):
    """Assert user-visible invariants, not private module layout."""

    def test_zip_first_apply_branch_verify_does_not_publish(self) -> None:
        selection = self.make_self_contained_zip()
        digest = hashlib.sha256(self.zip.read_bytes()).hexdigest()

        result = self.invoke_zip(
            "opSeq=APL,BRN,CHK,STS", "skipApproves=true", selection=selection,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(hashlib.sha256(self.zip.read_bytes()).hexdigest(), digest)
        self.assertEqual(self.root.joinpath("existing.txt").read_text(), "updated\n")
        self.assertEqual(self.root.joinpath("new.txt").read_text(), "new\n")
        self.assertEqual(
            command("git", "branch", "--show-current", cwd=self.root).stdout.strip(),
            self.payload["feature_branch"],
        )
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertEqual(record["phase"], "verified")
        self.assertEqual(record["archive_sha256"], digest)
        self.assertEqual(record["applied_branch"], self.payload["feature_branch"])
        self.assertEqual(len(self.history_path.read_text().split("Patch: ")) - 1, 1)
        self.assertFalse((self.root / ".git" / "refs" / "remotes" / "origin" /
                          self.payload["feature_branch"]).exists())

    def test_clean_worktree_is_a_non_bypassable_apply_precondition(self) -> None:
        selection = self.make_self_contained_zip()
        user_file = self.root / "user-notes.txt"
        user_file.write_text("Do not overwrite user data.\n")
        original = user_file.read_bytes()

        result = self.invoke_zip("op=APL", "skipApproves=true", selection=selection)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(user_file.read_bytes(), original)
        self.assertEqual((self.root / "existing.txt").read_text(), "old\n")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)

    def test_invalid_archive_member_never_writes_outside_target(self) -> None:
        selection = self.make_self_contained_zip()
        sentinel = self.base / "escape.txt"
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr("example_service/../../escape.txt", "unsafe\n")

        result = self.invoke_zip("op=APL", "skipApproves=true", selection=selection)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(sentinel.exists())
        self.assertEqual((self.root / "existing.txt").read_text(), "old\n")
        self.assertFalse((self.root / "new.txt").exists())

    def test_replaying_an_applied_zip_cannot_reapply_changes_unattended(self) -> None:
        selection = self.make_self_contained_zip()
        applied = self.invoke_zip("op=APL", "skipApproves=true", selection=selection)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        before_history = self.history_path.read_bytes()
        before_state = json.loads(self.state_path.read_text())

        replay = self.invoke_zip("op=APL", "skipApproves=true", selection=selection)

        self.assertNotEqual(replay.returncode, 0, replay.stdout)
        self.assertEqual(self.history_path.read_bytes(), before_history)
        self.assertEqual((self.root / "existing.txt").read_text(), "updated\n")
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")
        after_state = json.loads(self.state_path.read_text())
        self.assertEqual(
            {k: value["phase"] for k, value in after_state["workflows"].items()},
            {k: value["phase"] for k, value in before_state["workflows"].items()},
        )

    def test_failed_checks_never_create_a_local_commit(self) -> None:
        self.configure_checks(
            'schema_version: 1\nchecks:\n  - ["./run_checks.sh"]\n'
            '  - ["sh", "-c", "exit 7"]\n',
        )
        selection = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN,CHK,CMT", "skipApproves=true",
                                 selection=selection)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("SEQUENCE STOP", result.stdout)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip(),
                         self.head)
        record = next(iter(json.loads(self.state_path.read_text())["workflows"].values()))
        self.assertNotIn(record["phase"], {"committed", "pushed", "pr_created", "merged"})
        self.assertEqual((self.root / "new.txt").read_text(), "new\n")

    def test_status_and_audit_do_not_mutate_git_tree_or_refs(self) -> None:
        selection = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN", "skipApproves=true",
                                 selection=selection)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        branch = command("git", "branch", "--show-current", cwd=self.root).stdout
        head = command("git", "rev-parse", "HEAD", cwd=self.root).stdout
        status = command("git", "status", "--porcelain", cwd=self.root).stdout
        source = (self.root / "new.txt").read_bytes()

        inspection = self.invoke_zip("op=STS", "skipApproves=true")
        audit = self.invoke_zip("op=AUD", "skipApproves=true")

        self.assertEqual(inspection.returncode, 0, inspection.stdout + inspection.stderr)
        self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)
        self.assertEqual(command("git", "branch", "--show-current", cwd=self.root).stdout,
                         branch)
        self.assertEqual(command("git", "rev-parse", "HEAD", cwd=self.root).stdout, head)
        self.assertEqual(command("git", "status", "--porcelain", cwd=self.root).stdout,
                         status)
        self.assertEqual((self.root / "new.txt").read_bytes(), source)


if __name__ == "__main__":
    import unittest
    unittest.main()
