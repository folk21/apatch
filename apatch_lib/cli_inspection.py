"""Read-only CLI inspection and console helpers outside writable workflow dispatch."""

import time
from pathlib import Path

from .core.actions import ACTION_CODES, action_number
from .gitutil import current_branch
from .model import Abort, Config, Handoff
from .operation_events import unresolved_runs
from .progress import (ProgressEvent, ProgressRecorder, ProgressStore,
                       render_progress, utc_now)
from .reconciliation import audit_repository, format_audit
from .state import read_state_snapshot
from .status import display_status, inspect_patch, select_record


def show_status_with_progress(
    root: Path, config: Config, state: dict[str, object] | None,
    handoff: Handoff | None, patch: str | None, mode: str,
    recorder: ProgressRecorder, tool_dir: Path,
) -> None:
    """Report offline status and record an independent tool-wide STS event."""
    started_at = utc_now()
    started = time.monotonic()
    before_branch = current_branch(root)
    record: dict[str, object] = {}
    selected_patch = patch
    result, error = "FAILED", None
    try:
        if state is None:
            state = read_state_snapshot(config.state_path)
        show_unresolved_operations(state, root)
        record, selected_patch, planned = select_record(root, state, handoff, patch=patch)
        display_status(inspect_patch(root, config, record, selected_patch, planned, mode))
        result, error = "SUCCESS", None
    except (Abort, KeyboardInterrupt) as exc:
        result, error = "FAILED", exc
        raise
    finally:
        try:
            recorder.record(ProgressEvent.capture(
                root=root, patch_file=selected_patch,
                operation_number=10, mode=mode, result=result,
                phase_before=record.get("phase", "new"),
                phase_after=record.get("phase", "new"),
                branch_before=before_branch, branch_after=before_branch,
                record=record, started_at_utc=started_at,
                duration_seconds=time.monotonic() - started, error=error))
        except Exception as exc:
            print(f"WARNING: PROGRESS_UNAVAILABLE ({type(exc).__name__}); "
                  "the status result is unchanged.", flush=True)
        recorder.flush(tool_dir)


def show_audit_with_activity(
    root: Path, config: Config, tool_dir: Path, *, verify_remote: bool = False
) -> None:
    """Show recorded cross-project activity before the read-only repository audit."""
    try:
        print(render_progress(ProgressStore(tool_dir).read_snapshot(),
                              global_limit=config.progress_global_limit,
                              project_limit=config.progress_project_limit))
    except Abort as exc:
        print(f"WARNING: GLOBAL_PROGRESS_UNAVAILABLE ({type(exc).__name__}); "
              "repository audit remains available.")
    print()
    print(format_audit(audit_repository(root, config, verify_remote=verify_remote)))


def show_unresolved_operations(state: dict[str, object], root: Path) -> None:
    """Expose unfinished historical runs without changing persisted outcomes."""
    unfinished = unresolved_runs(state, root)
    if not unfinished:
        return
    print(f"WARNING: {len(unfinished)} operation run(s) remain STARTED in the project journal.")
    print("    A run may still be active or may have been interrupted; inspect current Git/PR state.")
    for run in unfinished[-3:]:
        print(f"    {run['run_id']} | {run['operation']['number']} "
              f"[{run['operation']['code']}] | patch={run['patch']}")


def select_without_handoff() -> int:
    """Allow repository-wide inspection before any handoff has been cached."""
    print("\nActions (* = requires an explicit ZIP/JSON handoff):")
    for number, code in enumerate(ACTION_CODES):
        if number == 0:
            label = "Exit"
        elif number == 10:
            label = "Inspect current patch status"
        elif number == 11:
            label = "Audit all known patch history"
        else:
            label = "Patch lifecycle action *"
        print(f" {number}. [{code}] {label}")
    try:
        selected = input("Choose an action (number or code): ").strip()
    except EOFError as exc:
        raise Abort("No action selected; use op=NUMBER or op=CODE") from exc
    try:
        return action_number(selected)
    except ValueError as exc:
        raise Abort(str(exc)) from exc
