"""Interactive, resumable local workflow with independent live Git guards."""

import hashlib
import logging
from copy import deepcopy
from pathlib import Path

from . import github
from .action_applicability import (ActionFacts, action_unavailable,
                                   DEPRECATED_BAP_REASON)
from .branch_patch import BranchPatchActions
from .console import outcome_label, terminal_style
from .core.actions import ACTION_CODES, action_number
from .core.enums import PHASE_VALUES, WorkflowPhase
from .core.contracts import ActionResult
from .force import ForceActions
from .loose import LooseActions
from .gitutil import (confirm, current_branch, head, is_clean, output, remote_head,
                      require_branch, require_clean, run, worktree_fingerprint)
from .model import Abort
from .operation_events import OperationRun, RunOutcome, journal_outcome_for_result
from .patch import inspect
from .patch_history import locked_history
from .presentation.execution import OperationPresentation
from .progress import utc_now
from .session import (attach_applied_workflow, create_feature_session,
                      remote_identity)
from .session_continuation import require_session_continuation
from .state import finish_run, save, start_run
from .gitutil import clear_confirmation_declined, confirmation_was_declined
from .zip_resume import handoff_signature, verify_applied_zip


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
        self._session_continuation_id = None
        self._goal_guarded_session_id = None
        self._goal_guarded_continuation = False
        self._goal_guarded_publication = False
        self.progress_recorder = progress_recorder
        self.progress_sequence = None
        self.operation_run_id = None
        self.operation_run_before = None
        self.operation_run_after = None
        key_data = f"{root.resolve()}\0{handoff.branch}\0{handoff.patch}"
        self.key = hashlib.sha256(key_data.encode()).hexdigest()
        self.record = state["workflows"].get(self.key, {})
        LOGGER.info("workflow loaded feature=%s patch=%s phase=%s", handoff.branch, handoff.patch, self.record.get("phase", "new"))
        signature = handoff_signature(handoff)
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

    def create_session(self):
        """Explicitly initialize a session; ordinary CLI actions do not invoke this."""
        if current_branch(self.root) not in {self.handoff.branch, self.config.base}:
            raise Abort("Feature session creation requires the intended feature or base branch")
        existing = deepcopy(self.state.get("feature_sessions"))
        try:
            session = create_feature_session(
                self.state, root=self.root, remote_name=self.config.remote,
                remote_url=output(["git", "remote", "get-url", self.config.remote], self.root),
                base_branch=self.config.base, feature_branch=self.handoff.branch,
                observed_head=head(self.root))
            save(self.config.state_path, self.state)
        except Exception:
            if existing is None:
                self.state.pop("feature_sessions", None)
            else:
                self.state["feature_sessions"] = existing
            raise
        return session

    def attach_session(self, session_id: str):
        """Opt in after recorded APL/BAP, under the existing project-state lock."""
        sessions = self.state.get("feature_sessions", {})
        session = sessions.get(session_id)
        if (session is None or session.get("remote_name") != self.config.remote
                or session.get("base_branch") != self.config.base
                or session.get("remote_identity") != remote_identity(
                    output(["git", "remote", "get-url", self.config.remote], self.root))):
            raise Abort("Feature session remote or base context cannot be verified")
        if current_branch(self.root) not in {self.handoff.branch, self.config.base}:
            raise Abort("Feature session requires the intended feature or configured base branch")
        if self.state["workflows"].get(self.key) is not self.record:
            raise Abort("Selected workflow is not a persisted checkpoint")
        if (self.record.get("handoff_signature") != self.signature
                or self.record.get("archive_sha256") != self.handoff.patch_sha256):
            raise Abort("Feature session link requires the verified selected ZIP identity")
        old_sessions = deepcopy(self.state.get("feature_sessions"))
        old_record = dict(self.record)
        try:
            with locked_history(self.config.applied_patches_path) as history:
                entries = [item for item in history.entries if item.patch == self.handoff.patch]
                if len(entries) != 1:
                    raise Abort("Feature session requires exactly one applied history entry")
                result = attach_applied_workflow(self.state, session_id, self.key,
                                                 history_entry=entries[0])
                save(self.config.state_path, self.state)
        except Exception:
            if old_sessions is None:
                self.state.pop("feature_sessions", None)
            else:
                self.state["feature_sessions"] = old_sessions
            self.record.clear()
            self.record.update(old_record)
            raise
        return result

    def apply_session_zip(self, session_id: str):
        """Internal FS-03 continuation path; no CLI dispatcher uses it yet.

        The goal planner may call this under the existing project-state lock.
        A confirmed APL is recorded before the new patch is linked to its session.
        """
        if not self.loose or self.force or not self.zip_selected or self.allow_followup_zip:
            raise Abort("Session continuation requires an explicitly selected new ZIP in LOOSE")
        if self.phase != WorkflowPhase.NEW or self._session_continuation_id is not None:
            raise Abort("Session continuation requires a new, unstarted patch workflow")
        require_session_continuation(self.root, self.config, self.handoff, session_id)
        self._session_continuation_id = session_id
        try:
            outcome = self.interactive("APL")
        finally:
            self._session_continuation_id = None
        if outcome == "SUCCESS":
            self.attach_session(session_id)
        return outcome

    def inspect_previous_cycles(self):
        """Offer a new patch cycle without changing any earlier checkpoint."""
        previous = [
            (key, record) for key, record in self.state["workflows"].items()
            if key != self.key and isinstance(record, dict)
            and record.get("repository") == str(self.root.resolve())
            and record.get("patch_file") != self.handoff.patch
            and record.get("phase") != "synced"
            and not record.get("superseded_by") and not record.get("continued_by")
        ]
        if not previous:
            return ()
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
        return tuple(key for key, _ in previous)

    def link_successful_previous_cycles(self, previous_keys):
        """Record additive continuation only after a new application is confirmed."""
        if not previous_keys:
            return
        with locked_history(self.config.applied_patches_path) as history:
            if (not history.entries or history.entries[-1].patch != self.handoff.patch
                    or history.entries[-1].planned_branch != self.handoff.branch
                    or history.entries[-1].real_branch != self.record.get("applied_branch")):
                print("WARNING: Previous-cycle linkage deferred: applied history is not "
                      "the expected latest patch. Inspect 11 [AUD].")
                return
        originals = {}
        for key in previous_keys:
            record = self.state["workflows"].get(key)
            if (not isinstance(record, dict) or record.get("continued_by")
                    or record.get("superseded_by") or record.get("phase") == "synced"
                    or record.get("branch") != self.handoff.branch):
                continue
            originals[key] = dict(record)
            record["continued_by"] = self.key
            record["continued_patch"] = self.handoff.patch
        if not originals:
            return
        try:
            save(self.config.state_path, self.state)
        except (Abort, OSError) as exc:
            for key, prior in originals.items():
                self.state["workflows"][key].clear()
                self.state["workflows"][key].update(prior)
            print(f"WARNING: Previous-cycle linkage was not saved ({type(exc).__name__}); "
                  "the newly applied patch remains recorded independently.")
            return
        LOGGER.info("linked %d unfinished workflow(s) to successfully applied patch=%s",
                    len(originals), self.handoff.patch)

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
        if number in {0, 10, 11}:
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
            failure = ActionResult.failed(exc, declined=confirmation_was_declined())
            outcome = (RunOutcome.INTERRUPTED.value if isinstance(exc, KeyboardInterrupt)
                       and failure.outcome.value == "ERROR"
                       else journal_outcome_for_result(failure.outcome))
            finish_run(self.config.state_path, self.state, run.data["run_id"],
                       outcome=outcome, before=self.operation_run_before,
                       after=self.operation_run_after or {"phase": self.phase})
            raise
        else:
            outcome = journal_outcome_for_result(result)
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

    def verified_resume_step(self, number: int) -> str | None:
        """Record a proven non-mutating APL/BRN satisfaction, never a new success."""
        if number not in {1, 3}:
            return None
        if self.phase in {"merged", "synced"}:
            raise Abort("Completed or merged ZIP cannot satisfy APL/BRN on the base branch")
        evidence = verify_applied_zip(self.root, self.config, self.handoff, self.state)
        if number == 1 and evidence.pending_branch:
            return None
        run = OperationRun.start(
            number=number, mode="FORCE" if self.force else "LOOSE" if self.loose else "STRICT",
            root=self.root, workflow_key=self.key, patch=self.handoff.patch,
            phase=self.phase, sequence=self.progress_sequence)
        start_run(self.config.state_path, self.state, run)
        finish_run(self.config.state_path, self.state, run.data["run_id"],
                   outcome=RunOutcome.NO_OP.value,
                   before={"phase": self.phase, "branch": evidence.branch},
                   after={"phase": self.phase, "branch": evidence.branch})
        self.operation_run_id = run.data["run_id"]
        try:
            self._record_progress(number, utc_now(), 0.0, "NO_OP", self.phase,
                                  evidence.branch, evidence.branch)
        finally:
            self.operation_run_id = None
        print(f"==> RESULT {number} [{ACTION_CODES[number]}]: "
              f"{terminal_style('ALREADY_SATISFIED', '33')} — verified selected ZIP; "
              "no Git or archive replay")
        return "ALREADY_SATISFIED"

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
                timeout=self.config.check_timeout_seconds,
                idle_timeout=self.config.check_idle_timeout_seconds)
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
        return self.push()

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
        run(["git", "push", "-u", self.config.remote, self.handoff.branch],
            self.root, timeout=self.config.github_timeout_seconds)
        if remote_head(self.root, self.config, self.handoff.branch) != head(self.root):
            raise Abort("Push returned but remote HEAD could not be verified")
        self.record.update(phase="pushed", pushed_sha=head(self.root))
        self.persist()
        print("Commit and push verified.")
        return True

    def pr(self):
        if self.phase != "pushed":
            raise Abort("Push is required before opening a PR")
        require_branch(self.root, self.handoff.branch)
        self.assert_remote_unchanged()
        return github.create_pr(self.config, self.handoff, self.root, self.record, self.persist)

    def merge(self):
        if self.phase != "pr_created":
            raise Abort("Open a PR before merge")
        require_branch(self.root, self.handoff.branch)
        self.assert_remote_unchanged()
        repo = github.merge_pr(self.config, self.handoff, self.root, self.record, self.persist)
        if self.phase == "merged":
            return github.sync_base(self.config, self.handoff, self.root, self.record, self.persist,
                                    verified_repo=repo)
        return None

    def sync(self):
        if self.phase != "merged":
            raise Abort("No confirmed GitHub merge needs synchronization")
        self.assert_remote_unchanged()
        return github.sync_base(self.config, self.handoff, self.root, self.record, self.persist)

    def options(self):
        pending_branch = (self.record.get("zip_first") is True
                          and self.record.get("applied_branch") == self.config.base)
        branch = current_branch(self.root)
        facts = ActionFacts(
            mode="force" if self.force else "loose" if self.loose else "strict",
            phase=self.phase, branch=branch, planned_branch=self.handoff.branch,
            applied_branch=self.applied_branch, base=self.config.base,
            clean=is_clean(self.root) if not (self.loose or self.force) else True,
            zip_selected=self.zip_selected, zip_first=self.record.get("zip_first") is True,
            zip_pending_branch=pending_branch,
            require_patch_feature_branch=self.config.require_patch_feature_branch)
        unavailable = lambda number: action_unavailable(number, facts)
        deprecated_bap = DEPRECATED_BAP_REASON if facts.zip_first else None
        if self.loose:
            actions = self.loose_actions
            guarded_session_id = self._goal_guarded_session_id
            check_action = ((lambda: actions.guarded_check(guarded_session_id))
                            if guarded_session_id else actions.verify)
            commit_action = ((lambda: actions.guarded_commit(guarded_session_id))
                             if guarded_session_id else actions.commit)
            return [
                ("Move applied patch to feature branch" if pending_branch else "Create/adopt a feature branch",
                 self.branch_patch.prepare_branch_after_apply if pending_branch else actions.prepare_branch,
                 unavailable(1)),
                ("Deprecated: apply-first ZIP workflows do not support BAP" if deprecated_bap
                 else "Create/adopt a feature branch and apply patch",
                 lambda: actions.prepare_branch(with_patch=True), unavailable(2)),
                (f"Apply another patch to current branch ({branch or 'detached HEAD'})",
                 actions.apply_patch, unavailable(3)),
                ("Run guarded goal checks" if guarded_session_id
                 else "Run/re-run canonical checks (allow manual edits)",
                 check_action, unavailable(4)),
                ("Commit verified goal scope" if guarded_session_id
                 else "Commit accumulated changes (do not push)",
                 commit_action, unavailable(5)),
                ("Push committed changes on current branch", actions.push, unavailable(6)),
                (f"Create/find PR for current patch branch -> {self.config.base}", actions.pr, unavailable(7)),
                (f"Merge PR into {self.config.base}", actions.merge, unavailable(8)),
                (f"Synchronize local {self.config.base} and reconcile PR status", actions.sync, unavailable(9)),
            ]
        if self.force:
            actions = self.force_actions
            return [
                ("Move applied patch to feature branch" if pending_branch else "Create/adopt a feature branch",
                 self.branch_patch.prepare_branch_after_apply if pending_branch else actions.prepare_branch,
                 unavailable(1)),
                ("Deprecated: apply-first ZIP workflows do not support BAP" if deprecated_bap
                 else "Create/adopt a feature branch and apply/adopt patch",
                 lambda: actions.prepare_branch(with_patch=True), unavailable(2)),
                (f"Apply/adopt patch on current branch ({branch or 'detached HEAD'})",
                 actions.apply_or_adopt, unavailable(3)),
                ("Run/re-run canonical checks", actions.verify, unavailable(4)),
                ("Commit and push current changes", actions.commit_push, unavailable(5)),
                ("Retry/reconcile push", actions.push, unavailable(6)),
                (f"Create/find PR for current patch branch -> {self.config.base}", actions.pr, unavailable(7)),
                (f"Merge PR into {self.config.base}", actions.merge, unavailable(8)),
                (f"Synchronize local {self.config.base} and reconcile PR status", actions.sync, unavailable(9)),
            ]
        return [
            ("Move applied patch to feature branch" if pending_branch else "Create a feature branch",
             self.branch_patch.prepare_branch_after_apply if pending_branch else lambda: self.branch_patch.new_branch(),
             unavailable(1)),
            ("Deprecated: apply-first ZIP workflows do not support BAP" if deprecated_bap
             else "Create a feature branch and apply patch", lambda: self.branch_patch.new_branch(True),
             unavailable(2)),
            (f"Apply patch to current branch ({branch or 'detached HEAD'})", self.branch_patch.unpack,
             unavailable(3)),
            ("Run/re-run canonical checks", self.verify,
             unavailable(4)),
            ("Commit and push all verified changes", self.commit_push,
             unavailable(5)),
            ("Retry push of the existing commit", self.push,
             unavailable(6)),
            (f"Create/find PR {self.handoff.branch} -> {self.config.base}", self.pr,
             unavailable(7)),
            (f"Merge PR into {self.config.base} and switch to {self.config.base}", self.merge,
             unavailable(8)),
            (f"Resume synchronization of local {self.config.base}", self.sync,
             unavailable(9)),
        ]
