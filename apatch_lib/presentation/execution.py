"""Presentation and outcome classification for existing workflow operations."""

import logging
import time

from ..console import outcome_label
from ..core.actions import ACTION_CODES, action_number
from ..core.enums import OperationOutcome
from ..gitutil import (clear_confirmation_declined, confirmation_was_declined,
                       current_branch, head, status_paths)
from ..model import Abort, RemoteOutcomeUnknown
from ..status import display_recommendation, inspect_patch


LOGGER = logging.getLogger("apatch.workflow")


class OperationPresentation:
    def menu_choice(self):
        self.print_header()
        options = self.options()
        print("\nActions (* = currently unavailable):")
        for index, (label, _, reason) in enumerate(options, start=1):
            suffix = f" * ({reason})" if reason else ""
            print(f" {index}. [{ACTION_CODES[index]}] {label}{suffix}")
        print(" 10. [STS] Inspect current patch status (read-only; offline)")
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
            display_status(inspect_patch(self.root, self.config, self.record,
                                         self.handoff.patch, self.handoff.branch,
                                         "loose" if self.loose else "force" if self.force else "strict"))
            return "NO_OP"
        options = self.options()
        label, operation, reason = options[number - 1]
        before_branch = current_branch(self.root)
        before_head = head(self.root)
        before_phase = self.phase
        before_paths = status_paths(self.root)
        print(f"\n==> START {number} [{ACTION_CODES[number]}]: {label}")
        print(f"    Branch: {before_branch or 'detached HEAD'} | Phase: {before_phase}")
        print(f"    Working-tree changes: {len(before_paths)} path(s)", flush=True)
        LOGGER.info("action selected feature=%s phase=%s action=%s", self.handoff.branch, self.phase, label)
        started = time.monotonic()
        clear_confirmation_declined()
        try:
            if reason:
                raise Abort(f"Action unavailable: {reason}")
            if number in {2, 3}:
                self.branch_patch.assert_patch_order()
            if not self.skip_previous_cycles:
                self.handle_previous_cycles()
            operation_evidence = operation()
        except (Abort, KeyboardInterrupt) as exc:
            elapsed = time.monotonic() - started
            result = ("CANCELLED" if confirmation_was_declined() else
                      "UNKNOWN_REMOTE_RESULT" if isinstance(exc, RemoteOutcomeUnknown) else "ERROR")
            print(f"\n==> RESULT {number} [{ACTION_CODES[number]}]: {outcome_label(result)} ({elapsed:.2f}s)")
            if result == "UNKNOWN_REMOTE_RESULT":
                print("    Remote side effect is unconfirmed. Inspect the matching GitHub PR "
                      "before retrying; no automatic replay is safe.")
            elif result == "ERROR":
                print("    Recovery: inspect 10 [STS] and the diagnostic below before resuming.")
            raise
        after_branch = current_branch(self.root)
        after_head = head(self.root)
        after_paths = status_paths(self.root)
        elapsed = time.monotonic() - started
        unchanged = (before_branch == after_branch and before_head == after_head
                     and before_phase == self.phase and before_paths == after_paths)
        verified_existing_sync = (number == 9 and unchanged and before_phase == "synced"
                                  and operation_evidence is True)
        repeated_verified_check = (number == 4 and unchanged and operation_evidence is True)
        result = (OperationOutcome.CANCELLED if confirmation_was_declined() else
                  OperationOutcome.ALREADY_SATISFIED if verified_existing_sync else
                  OperationOutcome.SUCCESS if number == 4 and operation_evidence is True else
                  OperationOutcome.NO_OP if unchanged else OperationOutcome.SUCCESS)
        print(f"\n==> RESULT {number} [{ACTION_CODES[number]}]: {outcome_label(result.value)} ({elapsed:.2f}s)")
        print(f"    Phase: {before_phase} -> {self.phase}")
        print(f"    Branch: {before_branch or 'detached HEAD'} -> {after_branch or 'detached HEAD'}")
        print(f"    HEAD: {before_head[:12]} -> {after_head[:12]}")
        print(f"    Working-tree changes: {len(before_paths)} -> {len(after_paths)} path(s)")
        if result == "CANCELLED":
            print("    A required confirmation was declined; later actions must not be inferred as safe.")
        elif verified_existing_sync:
            print("    Already synchronized; local base and matching merged PR were reverified.")
        elif repeated_verified_check:
            print("    Canonical checks passed again against the current repository snapshot.")
        elif unchanged:
            print("    No tracked workflow or Git-state transition detected; the action may have been "
                  "cancelled or already satisfied.")
        elif after_paths:
            preview = ", ".join(sorted(after_paths)[:10])
            remaining = len(after_paths) - min(len(after_paths), 10)
            print(f"    Changed paths: {preview}" + (f" (+{remaining} more)" if remaining else ""))
        if result not in {"SUCCESS", "ALREADY_SATISFIED"}:
            print("Next suggested: NONE — No completed action transition was confirmed; inspect status with 10 [STS].")
        else:
            display_recommendation(inspect_patch(self.root, self.config, self.record,
                                                  self.handoff.patch, self.handoff.branch,
                                                  "loose" if self.loose else "force" if self.force else "strict"))
        LOGGER.info("action completed feature=%s phase=%s action=%s", self.handoff.branch, self.phase, label)
        return result.value
