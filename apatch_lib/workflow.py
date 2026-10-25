"""Interactive, resumable local workflow with independent live Git guards."""

import hashlib
import json
import logging
from pathlib import Path

from . import github
from .branch_patch import BranchPatchActions
from .console import outcome_label
from .core.actions import ACTION_CODES, action_number
from .core.enums import PHASE_VALUES, WorkflowPhase
from .force import ForceActions
from .loose import LooseActions
from .gitutil import (confirm, current_branch, head, is_clean, output, remote_head,
                      require_branch, require_clean, run, worktree_fingerprint)
from .model import Abort
from .model import RemoteOutcomeUnknown
from .operation_events import OperationRun, RunOutcome
from .patch import inspect
from .patch_history import locked_history
from .presentation.execution import OperationPresentation
from .state import finish_run, save, start_run
from .gitutil import clear_confirmation_declined, confirmation_was_declined


LOGGER = logging.getLogger("apatch.workflow")

PHASES = PHASE_VALUES


class Workflow(OperationPresentation):
    def __init__(self, root: Path, config, handoff, state, *, force=False, loose=False,
                 skip_previous_cycles=False, zip_selected=False, allow_followup_zip=False,
                 progress_recorder=None):
        self.root = root
        self.config = config
        self.handoff = handoff
        self.state = state
        self.force = force
        self.loose = loose
        self.zip_selected = zip_selected
        self.allow_followup_zip = allow_followup_zip
        self.progress_recorder = progress_recorder
        self.progress_sequence = None
        self.operation_run_id = None
        self.operation_run_before = None
        self.operation_run_after = None
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
        if not skip_previous_cycles and self.record and self.record.get("handoff_signature") != signature:
            if not self.loose:
                raise Abort("Handoff JSON differs from the persisted workflow; do not mutate it mid-run")
            print("WARNING: Handoff JSON changed since this workflow was recorded.")
            if not confirm("LOOSE: Use the updated handoff for this patch cycle?"):
                raise Abort("Updated handoff was declined")
        if not skip_previous_cycles and self.record and (self.record.get("branch") != handoff.branch or
                            self.record.get("patch_file") != handoff.patch or
                            self.record.get("repository") != str(root.resolve())):
            raise Abort("State record identity mismatch")
        if not skip_previous_cycles and self.record.get("phase", "new") not in PHASES:
            raise Abort("Unknown persisted workflow phase")
        if not skip_previous_cycles and self.record.get("phase") == "applying":
            if not self.loose and not self.force:
                raise Abort("Previous extraction was interrupted; inspect worktree manually")
            print("WARNING: Previous extraction was interrupted; inspect files before another apply.")
        if self.record.get("phase") == "synced":
            print("This patch workflow has already completed.")
        self.branch_patch = BranchPatchActions(self)
        self.force_actions = ForceActions(self)
        self.loose_actions = LooseActions(self)
        self.skip_previous_cycles = skip_previous_cycles

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
        if self.loose:
            print("LOOSE: Keeping previous patch checkpoints and uncommitted changes. "
                  "Nothing is reset or discarded.")
        elif not confirm("Start a separate patch cycle and retain the previous checkpoints?"):
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

    def _verified_run_facts(self, number, outcome):
        """Keep only action-specific facts observed in the resulting checkpoint."""
        if outcome != RunOutcome.SUCCEEDED.value:
            return {}
        record = self.record
        facts = {}
        relevant = {
            1: ("applied_branch", "branch_origin"),
            2: ("archive_sha256", "applied_branch"),
            3: ("archive_sha256", "applied_branch"),
            4: ("verified_fingerprint", "verified_head", "verified_commit"),
            5: ("commit_sha", "pushed_sha"),
            6: ("pushed_sha",),
            7: ("pr_number",),
            8: ("pr_number", "merge_commit_sha"),
            9: ("pr_number",),
        }
        for key in relevant[number]:
            value = record.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                facts[key] = value
        if number == 9 and self.phase == "synced":
            facts["base_synchronized"] = True
        return facts

    def interactive(self, selected_op=None, *, show_header=True):
        """Persist a run around each action without introducing a nested state lock."""
        if selected_op is None:
            selected_op = self.menu_choice()
            show_header = False
        try:
            number = action_number(selected_op)
        except ValueError as exc:
            raise Abort(str(exc)) from exc
        if number in {0, 10}:
            return super().interactive(selected_op, show_header=show_header)
        run = OperationRun.start(
            number=number, mode="FORCE" if self.force else "LOOSE" if self.loose else "STRICT",
            root=self.root, workflow_key=self.key, patch=self.handoff.patch,
            phase=self.phase, sequence=self.progress_sequence)
        start_run(self.config.state_path, self.state, run)
        self.operation_run_id = run.data["run_id"]
        self.operation_run_before = {"phase": self.phase}
        self.operation_run_after = None
        clear_confirmation_declined()
        try:
            result = super().interactive(selected_op, show_header=show_header)
        except (Exception, KeyboardInterrupt) as exc:
            outcome = (RunOutcome.INDETERMINATE.value if isinstance(exc, RemoteOutcomeUnknown)
                       else RunOutcome.CANCELLED.value if confirmation_was_declined()
                       else RunOutcome.INTERRUPTED.value if isinstance(exc, KeyboardInterrupt)
                       else RunOutcome.FAILED.value)
            finish_run(self.config.state_path, self.state, run.data["run_id"],
                       outcome=outcome, before=self.operation_run_before,
                       after=self.operation_run_after or {"phase": self.phase})
            raise
        else:
            outcome = (RunOutcome.CANCELLED.value if result == "CANCELLED" else
                       RunOutcome.NO_OP.value if result in {"NO_OP", "ALREADY_SATISFIED"} else
                       RunOutcome.SUCCEEDED.value)
            finish_run(self.config.state_path, self.state, run.data["run_id"],
                       outcome=outcome, before=self.operation_run_before,
                       after=self.operation_run_after or {"phase": self.phase},
                       verified_facts=self._verified_run_facts(number, outcome))
            return result
        finally:
            self.operation_run_id = None
            self.operation_run_before = None
            self.operation_run_after = None

    def record_committed_branch(self):
        """Keep the applied-patch journal aligned with the current Git commit branch."""
        with locked_history(self.config.applied_patches_path) as history:
            history.record_commit_branch(self.handoff.patch, self.handoff.branch,
                                         current_branch(self.root))

    def assert_base(self):
        if self.handoff.base_commit and head(self.root) != self.handoff.base_commit:
            raise Abort(f"Base HEAD mismatch: expected {self.handoff.base_commit}, got {head(self.root)}")

    def assert_patch_identity(self):
        if (self.phase not in {WorkflowPhase.NEW, WorkflowPhase.BRANCH_CREATED, WorkflowPhase.APPLYING}
                and self.record.get("zip_first") and self.handoff.patch_sha256
                and self.record.get("archive_sha256") == self.handoff.patch_sha256
                and not (self.config.downloads / self.handoff.patch).exists()):
            return None
        archive = inspect(self.config, self.handoff, self.root,
                          before_apply=self.phase in {WorkflowPhase.NEW, WorkflowPhase.BRANCH_CREATED})
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
        if self.phase not in {WorkflowPhase.PATCH_APPLIED, WorkflowPhase.VERIFIED}:
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
            run(list(command), self.root, stream_output=True,
                timeout=self.config.check_timeout_seconds)
        after, _ = self.assert_expected_paths()
        if before != after:
            self.record["phase"] = WorkflowPhase.PATCH_APPLIED.value
            self.persist()
            raise Abort("Tests changed repository files; verification invalidated")
        self.record.update(phase="verified", verified_fingerprint=after)
        self.persist()
        print("Canonical checks passed for the current changed bytes. Review the diff before commit.")
        return True

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
        self.record_committed_branch()
        self.push()

    def push(self):
        if self.phase != "committed":
            raise Abort("There is no recorded commit awaiting push")
        require_branch(self.root, self.handoff.branch)
        require_clean(self.root)
        self.assert_remote_unchanged()
        if head(self.root) != self.record.get("commit_sha"):
            raise Abort("Recorded committed HEAD has changed")
        self.record_committed_branch()
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
        repo = github.merge_pr(self.config, self.handoff, self.root, self.record, self.persist)
        if self.phase == "merged":
            github.sync_base(self.config, self.handoff, self.root, self.record, self.persist,
                             verified_repo=repo)

    def sync(self):
        if self.phase != "merged":
            raise Abort("No confirmed GitHub merge needs synchronization")
        self.assert_remote_unchanged()
        github.sync_base(self.config, self.handoff, self.root, self.record, self.persist)

    def options(self):
        pending_branch = self.record.get("zip_first") and self.record.get("applied_branch") == self.config.base
        pending_reason = ("apply-first patch changes must be moved to a feature branch with 1 [BRN]"
                          if pending_branch else None)
        deprecated_bap = ("2 [BAP] is deprecated for self-contained ZIP workflows; use 3 [APL], then 1 [BRN]"
                          if self.record.get("zip_first") else None)
        if self.loose:
            branch = current_branch(self.root)
            actions = self.loose_actions
            return [
                ("Move applied patch to feature branch" if pending_branch else "Create/adopt a feature branch",
                 self.branch_patch.prepare_branch_after_apply if pending_branch else actions.prepare_branch, None),
                ("Deprecated: apply-first ZIP workflows do not support BAP" if deprecated_bap
                 else "Create/adopt a feature branch and apply patch",
                 lambda: actions.prepare_branch(with_patch=True), pending_reason or deprecated_bap),
                (f"Apply another patch to current branch ({branch or 'detached HEAD'})",
                 actions.apply_patch, pending_reason),
                ("Run/re-run canonical checks (allow manual edits)", actions.verify, pending_reason),
                ("Commit accumulated changes (do not push)", actions.commit, pending_reason),
                ("Push committed changes on current branch", actions.push, pending_reason),
                (f"Create/find PR for current patch branch -> {self.config.base}", actions.pr, pending_reason),
                (f"Merge PR into {self.config.base}", actions.merge, pending_reason),
                (f"Synchronize local {self.config.base} and reconcile PR status", actions.sync, pending_reason),
            ]
        if self.force:
            branch = current_branch(self.root)
            actions = self.force_actions
            return [
                ("Move applied patch to feature branch" if pending_branch else "Create/adopt a feature branch",
                 self.branch_patch.prepare_branch_after_apply if pending_branch else actions.prepare_branch, None),
                ("Deprecated: apply-first ZIP workflows do not support BAP" if deprecated_bap
                 else "Create/adopt a feature branch and apply/adopt patch",
                 lambda: actions.prepare_branch(with_patch=True), pending_reason or deprecated_bap),
                (f"Apply/adopt patch on current branch ({branch or 'detached HEAD'})",
                 actions.apply_or_adopt, pending_reason),
                ("Run/re-run canonical checks", actions.verify, pending_reason),
                ("Commit and push current changes", actions.commit_push, pending_reason),
                ("Retry/reconcile push", actions.push, pending_reason),
                (f"Create/find PR for current patch branch -> {self.config.base}", actions.pr, pending_reason),
                (f"Merge PR into {self.config.base}", actions.merge, pending_reason),
                (f"Synchronize local {self.config.base} and reconcile PR status", actions.sync, pending_reason),
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
            reason = unavailable((WorkflowPhase.NEW.value, WorkflowPhase.BRANCH_CREATED.value),
                                 self.handoff.branch if self.config.require_patch_feature_branch
                                 and not (phase == WorkflowPhase.NEW and branch == self.config.base and self.zip_selected)
                                 else None, True)
            return reason or ("requires a checked-out branch" if not branch else None)

        return [
            ("Move applied patch to feature branch" if pending_branch else "Create a feature branch",
             self.branch_patch.prepare_branch_after_apply if pending_branch else lambda: self.branch_patch.new_branch(),
             None if pending_branch else unavailable((WorkflowPhase.NEW.value,), self.config.base, True)),
            ("Deprecated: apply-first ZIP workflows do not support BAP" if deprecated_bap
             else "Create a feature branch and apply patch", lambda: self.branch_patch.new_branch(True),
             pending_reason or deprecated_bap or unavailable((WorkflowPhase.NEW.value,), self.config.base, True)),
            (f"Apply patch to current branch ({branch or 'detached HEAD'})", self.branch_patch.unpack,
             pending_reason or patch_unavailable()),
            ("Run/re-run canonical checks", self.verify,
             pending_reason or unavailable((WorkflowPhase.PATCH_APPLIED.value,
                                             WorkflowPhase.VERIFIED.value), self.applied_branch)),
            ("Commit and push all verified changes", self.commit_push,
             pending_reason or publish_unavailable()),
            ("Retry push of the existing commit", self.push,
             pending_reason or unavailable(("committed",), self.handoff.branch)),
            (f"Create/find PR {self.handoff.branch} -> {self.config.base}", self.pr,
             pending_reason or unavailable(("pushed",), self.handoff.branch)),
            (f"Merge PR into {self.config.base} and switch to {self.config.base}", self.merge,
             pending_reason or unavailable(("pr_created",), self.handoff.branch)),
            (f"Resume synchronization of local {self.config.base}", self.sync,
             pending_reason or unavailable(("merged",))),
        ]

