"""Presentation and outcome classification for existing workflow operations."""

import logging
import time

from ..action_executor import execute_workflow_action
from ..console import next_action_label, outcome_label
from ..core.actions import ACTION_CODES, action_number
from ..core.contracts import ActionResult
from ..core.enums import OperationOutcome
from ..gitutil import (clear_confirmation_declined, confirmation_was_declined,
                       current_branch, head, status_paths)
from ..model import Abort, CheckWorktreeChanged
from ..progress import ProgressEvent, utc_now
from ..status import display_recommendation, inspect_patch


LOGGER = logging.getLogger("apatch.workflow")


class OperationPresentation:
    def present_guarded_commit_readiness(self, session_id: str, *,
                                         accepted_manual_paths=()):
        """Show the future goal planner's commit gate without mutating state."""
        from ..context import inspect_guarded_commit_readiness

        readiness = inspect_guarded_commit_readiness(
            self, session_id, accepted_manual_paths=accepted_manual_paths)
        print(f"==> COMMIT GUARD {readiness.status}: {readiness.detail}")
        if readiness.paths:
            preview = ", ".join(readiness.paths[:10])
            extra = len(readiness.paths) - min(10, len(readiness.paths))
            print(f"    Scope: {preview}" + (f" (+{extra} more)" if extra else ""))
        if readiness.status == "NEEDS_VERIFICATION":
            print("    Recovery: Run guarded CHK on the exact scoped bytes before CMT.")
        elif readiness.status == "WAITING_FOR_USER":
            print("    Recovery: Review and explicitly accept each manual path.")
        return readiness

    def _record_progress(self, number, started_at, elapsed, result, before_phase,
                         before_branch, after_branch, *, error=None):
        recorder = getattr(self, "progress_recorder", None)
        if recorder is None:
            return
        try:
            recorder.record(ProgressEvent.capture(
                root=self.root, patch_file=self.handoff.patch, operation_number=number,
                mode="force" if self.force else "loose" if self.loose else "strict",
                result=result, phase_before=before_phase, phase_after=self.phase,
                branch_before=before_branch, branch_after=after_branch,
                record=self.record, started_at_utc=started_at, duration_seconds=elapsed,
                error=error, sequence=self.progress_sequence,
                event_id=getattr(self, "operation_run_id", None)))
        except Exception as exc:
            print(f"WARNING: PROGRESS_UNAVAILABLE ({type(exc).__name__}); "
                  "operation outcome is unchanged.", flush=True)

    def menu_choice(self):
        self.print_header()
        options = self.options()
        print("\nActions (* = currently unavailable):")
        for index, (label, _, reason) in enumerate(options, start=1):
            suffix = f" * ({reason})" if reason else ""
            print(f" {index}. [{ACTION_CODES[index]}] {label}{suffix}")
        print(" 10. [STS] Inspect current patch status (read-only; offline)")
        print(" 11. [AUD] Audit all known patch history (read-only; offline by default)")
        print(" 12. [FMT] Run configured formatters before CHK (preserves edits)")
        print(" 0. [EXT] Exit")
        try:
            return input("Choose an action (number or code): ").strip()
        except EOFError as exc:
            raise Abort("No action selected; use op=NUMBER or op=CODE to run non-interactively") from exc

    def print_header(self):
        print(f"\n-----\nRepository: {self.root}\nFeature branch: {self.handoff.branch}\n"
              f"Patch: {self.handoff.patch}\nPhase: {self.phase}\n"
              f"Current branch: {current_branch(self.root)}")
        if self.force:
            print("Mode: FORCE (manual recovery)")
        elif self.loose:
            print("Mode: LOOSE (default; supervised incremental workflow)")
        else:
            print("Mode: STRICT (guarded phase-by-phase workflow)")
        print(f"Base branch: {self.config.base} (source: {self.config.base_branch_source})")
        print("Available modes: LOOSE (default), STRICT, FORCE. Use --help for options.")
        print("-----")
        if self.force:
            print("FORCE bypasses workflow-phase checks, not Git integrity, archive safety, "
                  "non-fast-forward protection, or GitHub review/CI rules.")
        if self.loose:
            print("LOOSE allows pending changes and deferred commit/push; unsafe ZIP paths, "
                  "unreviewed overwrites, and non-fast-forward pushes remain protected.")

    def interactive(self, selected_op=None, *, show_header=True):
        if selected_op is not None and show_header:
            self.print_header()
        choice = self.menu_choice() if selected_op is None else str(selected_op).strip().upper()
        try:
            number = action_number(choice)
        except ValueError as exc:
            raise Abort(str(exc)) from exc
        if selected_op is not None:
            print(f"Selected action via op={choice} (#{number}, {ACTION_CODES[number]})")
        if number == 0:
            print("Exit selected. No action was run.")
            return "NO_OP"
        if number == 10:
            from ..status import display_status
            started_at = utc_now()
            started = time.monotonic()
            previous_phase = self.phase
            branch = current_branch(self.root)
            try:
                display_status(inspect_patch(self.root, self.config, self.record,
                                             self.handoff.patch, self.handoff.branch,
                                             "loose" if self.loose else "force" if self.force else "strict",
                                             zip_selected=getattr(self, "zip_selected", False)))
            except (Abort, KeyboardInterrupt) as exc:
                self._record_progress(number, started_at, time.monotonic() - started,
                                      "FAILED", previous_phase, branch, branch, error=exc)
                raise
            self._record_progress(number, started_at, time.monotonic() - started,
                                  "SUCCESS", previous_phase, branch, branch)
            return "NO_OP"
        if number == 11:
            from ..reconciliation import audit_repository, format_audit
            print(format_audit(audit_repository(self.root, self.config)))
            return "NO_OP"
        if number == 12:
            label, operation, reason = ("Run configured formatters before CHK",
                                        self.format, None)
        else:
            options = self.options()
            label, operation, reason = options[number - 1]
        before_branch = current_branch(self.root)
        before_head = head(self.root)
        before_phase = self.phase
        before_paths = status_paths(self.root)
        if getattr(self, "operation_run_id", None) is not None:
            self.operation_run_before = {"phase": before_phase, "branch": before_branch,
                                         "head": before_head}
        started_at = utc_now()
        print(f"\n==> START {number} [{ACTION_CODES[number]}]: {label}")
        print(f"    Branch: {before_branch or 'detached HEAD'} | Phase: {before_phase}")
        print(f"    Working-tree changes: {len(before_paths)} path(s)", flush=True)
        LOGGER.info("action selected feature=%s phase=%s action=%s", self.handoff.branch, self.phase, label)
        started = time.monotonic()
        clear_confirmation_declined()
        try:
            action_result = execute_workflow_action(self, number, operation, reason, before_phase)
        except (Abort, KeyboardInterrupt) as exc:
            elapsed = time.monotonic() - started
            failure = ActionResult.failed(exc, declined=confirmation_was_declined())
            result = failure.outcome.value
            print(f"\n==> RESULT {number} [{ACTION_CODES[number]}]: {outcome_label(result)} ({elapsed:.2f}s)")
            if result == "UNKNOWN_REMOTE_RESULT":
                print("    Remote side effect is unconfirmed. Inspect the matching GitHub PR "
                      "before retrying; no automatic replay is safe.")
            elif result == "ERROR":
                if isinstance(exc, CheckWorktreeChanged):
                    print(f"    Phase: {before_phase} -> {self.phase}")
                    print("    Project checks passed, but they changed the checked bytes. "
                          "Edits are preserved; verification is pending.")
                    print(f"==> {next_action_label(4, 'CHK')} — Review the check-produced edits, "
                          "then rerun verification.")
                    print("    Resume: apatch.sh opSeq=CHK,STS (do not reapply the ZIP).")
                else:
                    print("    Recovery: inspect 10 [STS] and the diagnostic below before resuming.")
            self._record_progress(number, started_at, elapsed,
                                  failure.progress_outcome,
                                  before_phase, before_branch, before_branch, error=exc)
            raise
        after_branch = current_branch(self.root)
        after_head = head(self.root)
        after_paths = status_paths(self.root)
        if getattr(self, "operation_run_id", None) is not None:
            self.operation_run_after = {"phase": self.phase, "branch": after_branch,
                                        "head": after_head}
        elapsed = time.monotonic() - started
        unchanged = (before_branch == after_branch and before_head == after_head
                     and before_phase == self.phase and before_paths == after_paths)
        if (action_result.outcome == OperationOutcome.NO_OP and not unchanged
                and not action_result.confirmed_partial_effect):
            error = Abort("UNCONFIRMED_LOCAL_RESULT: Git or workflow state changed without "
                          "explicit action completion evidence; inspect STS before retrying")
            print(f"\n==> RESULT {number} [{ACTION_CODES[number]}]: "
                  f"{outcome_label('ERROR')} ({elapsed:.2f}s)")
            print("    Local changes may have occurred; no successful completion was recorded.")
            print("    Recovery: inspect 10 [STS] and live Git state before retrying.")
            self._record_progress(number, started_at, elapsed, "FAILED", before_phase,
                                  before_branch, after_branch, error=error)
            raise error
        verified_existing_sync = (number == 9 and
                                  action_result.outcome == OperationOutcome.ALREADY_SATISFIED)
        repeated_verified_check = (number == 4 and unchanged and
                                   action_result.outcome == OperationOutcome.SUCCESS)
        confirmed_application = (number == 3 and action_result.outcome == OperationOutcome.SUCCESS)
        result = action_result.outcome.value
        print(f"\n==> RESULT {number} [{ACTION_CODES[number]}]: {outcome_label(result)} ({elapsed:.2f}s)")
        print(f"    Phase: {before_phase} -> {self.phase}")
        print(f"    Branch: {before_branch or 'detached HEAD'} -> {after_branch or 'detached HEAD'}")
        print(f"    HEAD: {before_head[:12]} -> {after_head[:12]}")
        print(f"    Working-tree changes: {len(before_paths)} -> {len(after_paths)} path(s)")
        if result == "CANCELLED":
            print("    A required confirmation was declined; later actions must not be inferred as safe.")
        elif action_result.confirmed_partial_effect:
            print(f"    Partial effect: {action_result.evidence}. Action completion is pending.")
        elif verified_existing_sync:
            print("    Already synchronized; local base and matching merged PR were reverified.")
        elif repeated_verified_check:
            print("    Canonical checks passed again against the current repository snapshot.")
        elif confirmed_application and unchanged:
            print("    Patch application/adoption completed and was checkpointed; "
                  "the changed-path list is unchanged.")
        elif unchanged and result == OperationOutcome.NO_OP.value:
            print("    The action reported no completed transition; inspect current status.")
        elif unchanged and result == OperationOutcome.SUCCESS.value:
            print("    The action confirmed completion without changing the local Git snapshot.")
        elif after_paths:
            preview = ", ".join(sorted(after_paths)[:10])
            remaining = len(after_paths) - min(len(after_paths), 10)
            print(f"    Changed paths: {preview}" + (f" (+{remaining} more)" if remaining else ""))
        if result not in {"SUCCESS", "ALREADY_SATISFIED"}:
            print("Next suggested: NONE — No completed action transition was confirmed; inspect status with 10 [STS].")
        else:
            display_recommendation(inspect_patch(self.root, self.config, self.record,
                                                  self.handoff.patch, self.handoff.branch,
                                                  "loose" if self.loose else "force" if self.force else "strict",
                                                  zip_selected=getattr(self, "zip_selected", False)))
        LOGGER.info("action completed feature=%s phase=%s action=%s", self.handoff.branch, self.phase, label)
        self._record_progress(number, started_at, elapsed, action_result.progress_outcome,
                              before_phase, before_branch, after_branch)
        return result
