"""Interactive, resumable local workflow with independent live Git guards."""

import hashlib
import json
import logging
from pathlib import Path

from . import github
from .branch_patch import BranchPatchActions
from .force import ForceActions
from .gitutil import (confirm, current_branch, head, is_clean, output, remote_head,
                      require_branch, require_clean, run, worktree_fingerprint)
from .model import Abort
from .patch import inspect
from .state import save


LOGGER = logging.getLogger("apatch.workflow")

PHASES = {"new", "branch_created", "applying", "patch_applied", "verified",
          "committed", "pushed", "pr_created", "merged", "synced"}


class Workflow:
    def __init__(self, root: Path, config, handoff, state, *, force=False):
        self.root = root
        self.config = config
        self.handoff = handoff
        self.state = state
        self.force = force
        key_data = f"{root.resolve()}\0{handoff.branch}\0{handoff.patch}"
        self.key = hashlib.sha256(key_data.encode()).hexdigest()
        self.record = state["workflows"].get(self.key, {})
        LOGGER.info("workflow loaded feature=%s patch=%s phase=%s", handoff.branch, handoff.patch, self.record.get("phase", "new"))
        signature = hashlib.sha256(json.dumps({
            "repository": handoff.repository, "branch": handoff.branch,
            "patch": handoff.patch, "message": handoff.message,
            "base": handoff.base_commit, "digest": handoff.patch_sha256,
            "deletes": handoff.delete_paths,
        }, sort_keys=True).encode()).hexdigest()
        self.signature = signature
        if self.record and self.record.get("handoff_signature") != signature:
            raise Abort("Handoff JSON differs from the persisted workflow; do not mutate it mid-run")
        if self.record and (self.record.get("branch") != handoff.branch or
                            self.record.get("patch_file") != handoff.patch or
                            self.record.get("repository") != str(root.resolve())):
            raise Abort("State record identity mismatch")
        if self.record.get("phase", "new") not in PHASES:
            raise Abort("Unknown persisted workflow phase")
        if self.record.get("phase") == "applying":
            raise Abort("Previous extraction was interrupted; inspect worktree manually")
        if self.record.get("phase") == "synced":
            print("This patch workflow has already completed.")
        self.branch_patch = BranchPatchActions(self)
        self.force_actions = ForceActions(self)
        self.handle_previous_cycles()

    def handle_previous_cycles(self):
        """Keep older checkpoints but explicitly acknowledge switching patch cycles."""
        previous = [
            (key, record) for key, record in self.state["workflows"].items()
            if key != self.key and isinstance(record, dict)
            and record.get("repository") == str(self.root.resolve())
            and record.get("patch_file") != self.handoff.patch
            and record.get("phase") != "synced" and not record.get("superseded_by")
        ]
        if not previous:
            return
        print("\nUnfinished workflows for this repository:")
        for _, record in previous:
            print(f"  {record.get('patch_file')} | branch={record.get('branch')} "
                  f"| phase={record.get('phase', 'new')}")
        print(f"New patch: {self.handoff.patch}")
        if not confirm("Start a separate patch cycle and retain the previous checkpoints?"):
            raise Abort("New patch cycle cancelled; previous checkpoints are unchanged")
        for _, record in previous:
            record["superseded_by"] = self.key
            record["superseded_patch"] = self.handoff.patch
        save(self.config.state_path, self.state)
        LOGGER.warning("superseded %d unfinished workflow(s) with patch=%s",
                       len(previous), self.handoff.patch)

    @property
    def phase(self):
        return self.record.get("phase", "new")

    @property
    def applied_branch(self):
        return self.record.get("applied_branch", self.handoff.branch)

    def persist(self):
        self.record.update(repository=str(self.root.resolve()), branch=self.handoff.branch,
                           patch_file=self.handoff.patch, handoff_signature=self.signature)
        self.state["workflows"][self.key] = self.record
        save(self.config.state_path, self.state)
        LOGGER.info("checkpoint saved feature=%s phase=%s", self.handoff.branch, self.phase)

    def assert_base(self):
        if self.handoff.base_commit and head(self.root) != self.handoff.base_commit:
            raise Abort(f"Base HEAD mismatch: expected {self.handoff.base_commit}, got {head(self.root)}")

    def assert_patch_identity(self):
        archive = inspect(self.config, self.handoff, self.root,
                          before_apply=self.phase in {"new", "branch_created"})
        saved = self.record.get("archive_sha256")
        if saved and saved != archive.sha256:
            raise Abort("Patch bytes changed since the last workflow step")
        return archive

    def assert_expected_paths(self):
        fingerprint, paths = worktree_fingerprint(self.root)
        expected = set(self.record.get("changed_paths", []))
        if not paths or set(paths) != expected:
            raise Abort(f"Unexpected changed files. Expected {sorted(expected)}, got {sorted(paths)}")
        return fingerprint, paths

    def assert_remote_unchanged(self):
        current = output(["git", "remote", "get-url", self.config.remote], self.root)
        expected = self.record.get("remote_url")
        if expected and current != expected:
            raise Abort("Git remote URL has changed since the workflow began")
        return current

    def verify(self):
        if self.phase not in {"patch_applied", "verified"}:
            raise Abort("There is no uncommitted applied patch to verify")
        require_branch(self.root, self.applied_branch)
        self.assert_remote_unchanged()
        if head(self.root) != self.record.get("before_patch_head"):
            raise Abort("HEAD drifted after patch application")
        self.assert_patch_identity()
        before, _ = self.assert_expected_paths()
        run(["git", "diff", "--check"], self.root)
        if not self.config.checks:
            raise Abort("No project verification commands configured")
        for command in self.config.checks:
            run(list(command), self.root, stream_output=True)
        after, _ = self.assert_expected_paths()
        if before != after:
            self.record["phase"] = "patch_applied"
            self.persist()
            raise Abort("Tests changed repository files; verification invalidated")
        self.record.update(phase="verified", verified_fingerprint=after)
        self.persist()
        print("Canonical checks passed for the current changed bytes. Review the diff before commit.")

    def commit_push(self):
        if self.phase != "verified":
            raise Abort("Run verification before commit")
        if self.applied_branch != self.handoff.branch:
            raise Abort("Automated commit/push requires a patch applied to the configured feature branch")
        require_branch(self.root, self.handoff.branch)
        self.assert_remote_unchanged()
        if head(self.root) != self.record["before_patch_head"]:
            raise Abort("HEAD changed since verification")
        actual, paths = self.assert_expected_paths()
        if actual != self.record.get("verified_fingerprint"):
            raise Abort("Changed files no longer match the verified bytes")
        self.assert_patch_identity()
        print("Changed paths:")
        for filename in sorted(paths):
            print(f"  {paths[filename]} {filename}")
        run(["git", "diff", "--stat"], self.root)
        print("Commit message:\n" + self.handoff.message)
        print("Push remote:", output(["git", "remote", "get-url", self.config.remote], self.root))
        if not confirm("Commit ALL listed modified/new/deleted files and push?"):
            return
        run(["git", "add", "-A"], self.root)
        staged_bytes = run(["git", "diff", "--cached", "--name-only", "-z"], self.root).stdout
        staged = set(filter(None, staged_bytes.split("\x00")))
        if staged != set(paths):
            raise Abort(f"Staged file set mismatch: {sorted(staged)} != {sorted(paths)}")
        run(["git", "diff", "--cached", "--check"], self.root)
        run(["git", "diff", "--cached", "--stat"], self.root)
        if not confirm("Staged paths reviewed; commit these exact files?"):
            return
        run(["git", "commit", "-F", "-"], self.root, input_text=self.handoff.message,
            log_commit_message=self.handoff.message)
        if output(["git", "rev-parse", "HEAD^"], self.root) != self.record["before_patch_head"]:
            raise Abort("New commit has an unexpected parent")
        actual_message = run(["git", "log", "-1", "--format=%B"], self.root).stdout.rstrip() + "\n"
        if actual_message != self.handoff.message:
            raise Abort("New commit message differs from the approved handoff")
        require_clean(self.root)
        self.record.update(phase="committed", commit_sha=head(self.root))
        self.persist()
        self.push()

    def push(self):
        if self.phase != "committed":
            raise Abort("There is no recorded commit awaiting push")
        require_branch(self.root, self.handoff.branch)
        require_clean(self.root)
        self.assert_remote_unchanged()
        if head(self.root) != self.record.get("commit_sha"):
            raise Abort("Recorded committed HEAD has changed")
        remote = remote_head(self.root, self.config, self.handoff.branch)
        allowed = {self.record.get("remote_before_patch_head"), self.record.get("commit_sha")}
        if remote not in allowed:
            raise Abort("Remote feature branch has unexpected history; refusing push")
        run(["git", "push", "-u", self.config.remote, self.handoff.branch], self.root)
        if remote_head(self.root, self.config, self.handoff.branch) != head(self.root):
            raise Abort("Push returned but remote HEAD could not be verified")
        self.record.update(phase="pushed", pushed_sha=head(self.root))
        self.persist()
        print("Commit and push verified.")

    def pr(self):
        if self.phase != "pushed":
            raise Abort("Push is required before opening a PR")
        require_branch(self.root, self.handoff.branch)
        self.assert_remote_unchanged()
        github.create_pr(self.config, self.handoff, self.root, self.record, self.persist)

    def merge(self):
        if self.phase != "pr_created":
            raise Abort("Open a PR before merge")
        require_branch(self.root, self.handoff.branch)
        self.assert_remote_unchanged()
        github.merge_pr(self.config, self.handoff, self.root, self.record, self.persist)
        if self.phase == "merged":
            github.sync_base(self.config, self.handoff, self.root, self.record, self.persist)

    def sync(self):
        if self.phase != "merged":
            raise Abort("No confirmed GitHub merge needs synchronization")
        self.assert_remote_unchanged()
        github.sync_base(self.config, self.handoff, self.root, self.record, self.persist)

    def options(self):
        if self.force:
            branch = current_branch(self.root)
            actions = self.force_actions
            return [
                ("Create/adopt a feature branch", actions.prepare_branch, None),
                ("Create/adopt a feature branch and apply/adopt patch",
                 lambda: actions.prepare_branch(with_patch=True), None),
                (f"Apply/adopt patch on current branch ({branch or 'detached HEAD'})",
                 actions.apply_or_adopt, None),
                ("Run/re-run canonical checks", actions.verify, None),
                ("Commit and push current changes", actions.commit_push, None),
                ("Retry/reconcile push", actions.push, None),
                (f"Create/find PR for current patch branch -> {self.config.base}", actions.pr, None),
                (f"Merge PR into {self.config.base}", actions.merge, None),
                (f"Synchronize local {self.config.base} after merge", actions.sync, None),
            ]
        phase = self.phase
        branch = current_branch(self.root)
        clean = is_clean(self.root)

        def unavailable(phases, required_branch=None, require_clean=False):
            if phase not in phases:
                return f"requires phase: {', '.join(phases)}"
            if required_branch is not None and branch != required_branch:
                return f"requires current branch: {required_branch}"
            if require_clean and not clean:
                return "requires a clean working tree"
            return None

        def publish_unavailable():
            reason = unavailable(("verified",))
            if reason:
                return reason
            if self.applied_branch != self.handoff.branch:
                return f"patch was applied to {self.applied_branch}; automated publishing requires {self.handoff.branch}"
            return unavailable(("verified",), self.handoff.branch)

        def patch_unavailable():
            reason = unavailable(("new", "branch_created"),
                                 self.handoff.branch if self.config.require_patch_feature_branch else None, True)
            return reason or ("requires a checked-out branch" if not branch else None)

        return [
            ("Create a feature branch", lambda: self.branch_patch.new_branch(),
             unavailable(("new",), self.config.base, True)),
            ("Create a feature branch and apply patch", lambda: self.branch_patch.new_branch(True),
             unavailable(("new",), self.config.base, True)),
            (f"Apply patch to current branch ({branch or 'detached HEAD'})", self.branch_patch.unpack,
             patch_unavailable()),
            ("Run/re-run canonical checks", self.verify,
             unavailable(("patch_applied", "verified"), self.applied_branch)),
            ("Commit and push all verified changes", self.commit_push,
             publish_unavailable()),
            ("Retry push of the existing commit", self.push,
             unavailable(("committed",), self.handoff.branch)),
            (f"Create/find PR {self.handoff.branch} -> {self.config.base}", self.pr,
             unavailable(("pushed",), self.handoff.branch)),
            (f"Merge PR into {self.config.base} and switch to {self.config.base}", self.merge,
             unavailable(("pr_created",), self.handoff.branch)),
            (f"Resume synchronization of local {self.config.base}", self.sync,
             unavailable(("merged",))),
        ]

    def interactive(self):
        print(f"\n-----\nRepository: {self.root}\nFeature branch: {self.handoff.branch}\n"
              f"Patch: {self.handoff.patch}\nPhase: {self.phase}\n"
              f"Current branch: {current_branch(self.root)}")
        if self.force:
            print("Mode: FORCE (manual recovery)")
        print("-----")
        if self.force:
            print("FORCE bypasses workflow-phase checks, not Git integrity, archive safety, "
                  "non-fast-forward protection, or GitHub review/CI rules.")
        options = self.options()
        print("\nActions (* = currently unavailable):")
        for index, (label, _, reason) in enumerate(options, start=1):
            suffix = f" * ({reason})" if reason else ""
            print(f" {index}. {label}{suffix}")
        print(" 0. Exit")
        choice = input("Choose an action: ").strip()
        if choice == "0":
            return
        if not choice.isdigit() or not (1 <= int(choice) <= len(options)):
            raise Abort("Invalid selection")
        label, operation, reason = options[int(choice) - 1]
        if reason:
            raise Abort(f"Action unavailable: {reason}")
        LOGGER.info("action selected feature=%s phase=%s action=%s", self.handoff.branch, self.phase, label)
        operation()
        LOGGER.info("action completed feature=%s phase=%s action=%s", self.handoff.branch, self.phase, label)
