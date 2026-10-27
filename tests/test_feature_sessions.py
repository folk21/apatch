"""Feature session persistence, legacy migration, and explicit linkage safety."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apatch_lib.model import Abort, load_config, load_project_config
from apatch_lib.params_cache import load_cached_handoff
from apatch_lib.session import (
    close_feature_session, create_feature_session,
    record_session_commit, record_session_head, record_session_pr, remote_identity,
)
from apatch_lib.state import locked_state, read_state_snapshot, save
from apatch_lib.workflow import Workflow
from tests._support import LocalGitFixture, TOOL, command


class SessionStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        self.state_path = self.root / ".apatch" / "apply_patch.state.json"
        self.state_path.parent.mkdir()

    def create(self, state, branch="feature/example"):
        return create_feature_session(
            state, root=self.root, remote_name="origin", remote_url="local-test-remote",
            base_branch="main", feature_branch=branch,
            observed_head="a" * 40)

    def test_v1_v2_migrate_without_rewriting_until_explicit_mutation(self):
        for schema in (1, 2):
            with self.subTest(schema=schema):
                original = {
                    "schema_version": schema,
                    "workflows": {"legacy": {"phase": "synced", "superseded_by": "old"}},
                    "future_extension": {"keep": [1, 2]},
                }
                if schema == 2:
                    original["operation_runs"] = []
                self.state_path.write_text(json.dumps(original))
                before = self.state_path.read_bytes()
                snapshot = read_state_snapshot(self.state_path)
                self.assertNotIn("feature_sessions", snapshot)
                self.assertEqual(self.state_path.read_bytes(), before)
                with locked_state(self.state_path) as state:
                    session = self.create(state)
                    save(self.state_path, state)
                migrated = read_state_snapshot(self.state_path)
                self.assertEqual(migrated["schema_version"], 2)
                self.assertEqual(migrated["future_extension"], original["future_extension"])
                self.assertEqual(migrated["workflows"], original["workflows"])
                self.assertEqual(migrated["operation_runs"], [])
                self.assertIn(session.session_id, migrated["feature_sessions"])

    def test_explicit_identity_is_stable_and_credentials_are_not_persisted(self):
        credentialed_url = "https://user:private@example.test/owner/repo.git"
        private_root = self.root / "private"
        private_root.mkdir()
        with locked_state(self.state_path) as state:
            session = create_feature_session(
                state, root=private_root, remote_name="origin",
                remote_url=credentialed_url,
                base_branch="main", feature_branch="feature/one")
            save(self.state_path, state)
        content = self.state_path.read_text()
        self.assertNotIn(credentialed_url, content)
        self.assertNotIn("user:private@", content)
        stored = json.loads(content)["feature_sessions"][session.session_id]
        self.assertNotIn("remote_url", stored)
        self.assertEqual(stored["repository"], str(private_root.resolve()))
        self.assertEqual(len(session.session_id), 32)
        self.assertEqual(session.remote_identity, remote_identity(credentialed_url))
        self.assertEqual(read_state_snapshot(self.state_path)["feature_sessions"]
                         [session.session_id]["session_id"], session.session_id)

    def test_active_branch_conflict_but_terminal_branch_reuse_is_distinct(self):
        with locked_state(self.state_path) as state:
            first = self.create(state)
            with self.assertRaisesRegex(Abort, "already owns"):
                self.create(state)
            record_session_pr(state, first.session_id, number=8,
                              head_sha="a" * 40, status="MERGED")
            close_feature_session(state, first.session_id, status="merged",
                                  pr_number=8, merge_sha="b" * 40)
            second = self.create(state)
            save(self.state_path, state)
        self.assertNotEqual(first.session_id, second.session_id)
        result = read_state_snapshot(self.state_path)["feature_sessions"]
        self.assertEqual(result[first.session_id]["status"], "merged")
        self.assertEqual(result[second.session_id]["status"], "active")

    def test_opaque_commits_and_pr_revisions_append_without_mutating_journal(self):
        with locked_state(self.state_path) as state:
            item = self.create(state)
            record_session_commit(state, item.session_id, "a" * 40)
            record_session_commit(state, item.session_id, "a" * 40)
            record_session_head(state, item.session_id, "b" * 40)
            record_session_head(state, item.session_id, "b" * 40)
            record_session_pr(state, item.session_id, number=3,
                              head_sha="a" * 40, status="OPEN")
            record_session_pr(state, item.session_id, number=3,
                              head_sha="b" * 40, status="OPEN")
            record_session_pr(state, item.session_id, number=3,
                              head_sha="b" * 40, status="MERGED")
            record_session_pr(state, item.session_id, number=3,
                              head_sha="b" * 40, status="OPEN")
            save(self.state_path, state)
        stored = read_state_snapshot(self.state_path)
        self.assertEqual(stored["feature_sessions"][item.session_id]["commit_shas"], ["a" * 40])
        self.assertEqual(len(stored["feature_sessions"][item.session_id]["pr_revisions"]), 3)
        self.assertEqual(stored["feature_sessions"][item.session_id]["observed_heads"],
                         ["a" * 40, "b" * 40])
        self.assertEqual(stored["operation_runs"], [])
        self.assertEqual(stored["workflows"], {})

    def test_malformed_sessions_fail_closed_and_leave_source_unchanged(self):
        with locked_state(self.state_path) as state:
            item = self.create(state)
            save(self.state_path, state)
        healthy = json.loads(self.state_path.read_text())
        entry = healthy["feature_sessions"][item.session_id]
        variants = []
        bad = copy.deepcopy(healthy)
        bad["feature_sessions"][item.session_id]["status"] = ["active"]
        variants.append(bad)
        bad = copy.deepcopy(healthy)
        bad["feature_sessions"][item.session_id]["commit_shas"] = ["short"]
        variants.append(bad)
        bad = copy.deepcopy(healthy)
        bad["feature_sessions"][item.session_id]["patch_workflow_keys"] = ["absent"]
        variants.append(bad)
        bad = copy.deepcopy(healthy)
        bad["feature_sessions"][item.session_id]["observed_heads"] = ["a" * 40] * 2
        variants.append(bad)
        bad = copy.deepcopy(healthy)
        bad["feature_sessions"][item.session_id]["terminal_evidence"] = {"kind": "MERGED_PR"}
        variants.append(bad)
        bad = copy.deepcopy(healthy)
        bad["feature_sessions"][item.session_id]["remote_identity"] = "raw-remote-url"
        variants.append(bad)
        bad = copy.deepcopy(healthy)
        bad["workflows"]["forged"] = {
            "repository": str(self.root), "branch": "feature/example",
            "session_id": item.session_id,
        }
        variants.append(bad)
        bad = copy.deepcopy(healthy)
        bad["schema_version"] = 3
        variants.append(bad)
        self.assertNotIn("terminal_evidence", entry)
        for bad in variants:
            with self.subTest(bad=bad):
                self.state_path.write_text(json.dumps(bad))
                original = self.state_path.read_bytes()
                with self.assertRaises(Abort):
                    with locked_state(self.state_path) as state:
                        save(self.state_path, state)
                self.assertEqual(self.state_path.read_bytes(), original)

    def test_interrupted_atomic_write_preserves_prior_bytes(self):
        with locked_state(self.state_path) as state:
            self.create(state)
            save(self.state_path, state)
        before = self.state_path.read_bytes()
        with locked_state(self.state_path) as state:
            self.create(state, branch="feature/second")
            with patch("apatch_lib.state.os.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    save(self.state_path, state)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(len(read_state_snapshot(self.state_path)["feature_sessions"]), 1)

    def test_concurrent_writers_preserve_independent_sessions(self):
        worker = (
            "from pathlib import Path\n"
            "from apatch_lib.state import locked_state, save\n"
            "from apatch_lib.session import create_feature_session\n"
            "import sys, time\n"
            "root = Path(sys.argv[1])\n"
            "target = root / '.apatch/apply_patch.state.json'\n"
            "with locked_state(target) as state:\n"
            "    create_feature_session(state, root=root, remote_name='origin', "
            "remote_url='local-test-remote', base_branch='main', "
            "feature_branch='feature/' + sys.argv[2])\n"
            "    time.sleep(0.03)\n"
            "    save(target, state)\n"
        )
        processes = [subprocess.Popen([sys.executable, "-B", "-c", worker,
                                       str(self.root), str(index)], cwd=TOOL,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True) for index in range(4)]
        for process in processes:
            out, err = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, (out, err))
        sessions = read_state_snapshot(self.state_path)["feature_sessions"]
        self.assertEqual(len(sessions), 4)
        self.assertEqual(len({item["session_id"] for item in sessions.values()}), 4)


class SessionWorkflowTests(LocalGitFixture):
    def config(self):
        return load_project_config(self.root, load_config(self.bin))

    def workflow(self):
        return Workflow(self.root, self.config(), load_cached_handoff(self.root),
                        read_state_snapshot(self.state_path), loose=True,
                        skip_previous_cycles=True)

    def test_opt_in_two_applied_zips_one_commit_keeps_original_journal(self):
        first = self.make_self_contained_zip()
        applied = self.invoke_zip("opSeq=APL,BRN", "skipApproves=true", selection=first)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        with locked_state(self.state_path) as state:
            w = Workflow(self.root, self.config(), load_cached_handoff(self.root),
                         state, loose=True, skip_previous_cycles=True)
            session = w.create_session()
            self.assertEqual(w.attach_session(session.session_id).patch_workflow_keys, (w.key,))
        history_before = self.history_path.read_bytes()
        runs_before = len(read_state_snapshot(self.state_path)["operation_runs"])
        second = self.make_followup_zip()
        followup = self.invoke_zip("op=APL", "followup=true", "skipApproves=true",
                                   selection=second.stem)
        self.assertEqual(followup.returncode, 0, followup.stdout + followup.stderr)
        with locked_state(self.state_path) as state:
            w = Workflow(self.root, self.config(), load_cached_handoff(self.root),
                         state, loose=True, skip_previous_cycles=True)
            self.assertEqual(len(w.attach_session(session.session_id).patch_workflow_keys), 2)
            self.assertEqual(len(w.attach_session(session.session_id).patch_workflow_keys), 2)
        self.assertEqual(len(self.history_path.read_text().split("Date: ")) - 1, 2)
        committed = self.invoke_zip("op=CMT", "skipApproves=true")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        sha = command("git", "rev-parse", "HEAD", cwd=self.root).stdout.strip()
        with locked_state(self.state_path) as state:
            item = record_session_commit(state, session.session_id, sha)
            save(self.state_path, state)
        self.assertEqual(item.commit_shas, (sha,))
        updated = read_state_snapshot(self.state_path)
        self.assertEqual({updated["workflows"][key]["commit_sha"]
                          for key in item.patch_workflow_keys}, {sha})
        self.assertEqual(updated["feature_sessions"][session.session_id]["status"], "active")
        self.assertEqual(len(updated["operation_runs"]), runs_before + 2)
        self.assertNotEqual(self.history_path.read_bytes(), history_before)

    def test_regular_cli_does_not_auto_create_a_feature_session(self):
        stem = self.make_self_contained_zip()
        result = self.invoke_zip("opSeq=APL,BRN,CHK", "skipApproves=true", selection=stem)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        snapshot = read_state_snapshot(self.state_path)
        self.assertNotIn("feature_sessions", snapshot)
        self.assertFalse(any("session_id" in item for item in snapshot["workflows"].values()))

    def test_history_or_successful_application_evidence_cannot_be_forged(self):
        stem = self.make_self_contained_zip()
        self.assertEqual(self.invoke_zip("op=APL", "skipApproves=true",
                                         selection=stem).returncode, 0)
        with locked_state(self.state_path) as state:
            w = Workflow(self.root, self.config(), load_cached_handoff(self.root),
                         state, loose=True, skip_previous_cycles=True)
            session = w.create_session()
            run = next(run for run in state["operation_runs"] if run["operation"]["number"] == 3)
            original = run["verified_facts"]["archive_sha256"]
            run["verified_facts"]["archive_sha256"] = "b" * 64
            with self.assertRaisesRegex(Abort, "successful recorded application"):
                w.attach_session(session.session_id)
            run["verified_facts"]["archive_sha256"] = original
            self.assertNotIn("session_id", w.record)
            self.assertEqual(state["feature_sessions"][session.session_id]["patch_workflow_keys"], [])

    def test_unapplied_and_changed_remote_cannot_be_associated(self):
        stem = self.make_self_contained_zip()
        applied = self.invoke_zip("op=APL", "skipApproves=true", selection=stem)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        with locked_state(self.state_path) as state:
            w = Workflow(self.root, self.config(), load_cached_handoff(self.root),
                         state, loose=True, skip_previous_cycles=True)
            session = w.create_session()
        command("git", "remote", "set-url", "origin", str(self.base / "changed.git"), cwd=self.root)
        before = self.state_path.read_bytes()
        with locked_state(self.state_path) as state:
            w = Workflow(self.root, self.config(), load_cached_handoff(self.root),
                         state, loose=True, skip_previous_cycles=True)
            with self.assertRaisesRegex(Abort, "remote or base"):
                w.attach_session(session.session_id)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_failed_save_rolls_back_in_memory_link(self):
        stem = self.make_self_contained_zip()
        self.assertEqual(self.invoke_zip("op=APL", "skipApproves=true",
                                         selection=stem).returncode, 0)
        with locked_state(self.state_path) as state:
            w = Workflow(self.root, self.config(), load_cached_handoff(self.root),
                         state, loose=True, skip_previous_cycles=True)
            session = w.create_session()
            before = self.state_path.read_bytes()
            with patch("apatch_lib.workflow.save", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(Abort, "disk full"):
                    w.attach_session(session.session_id)
            self.assertNotIn("session_id", w.record)
            self.assertEqual(state["feature_sessions"][session.session_id]["patch_workflow_keys"], [])
            self.assertEqual(self.state_path.read_bytes(), before)
