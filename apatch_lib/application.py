"""Coordinate CLI requests without owning argument grammar or handoff parsing."""

import logging
from dataclasses import dataclass
from pathlib import Path

from .cli_inspection import (select_without_handoff, show_audit_with_activity,
                             show_status_with_progress, show_unresolved_operations)
from .cli_request import (CliRequest, validate_progress_request,
                          validate_repository_request)
from .branch_reassignment import reassign_pending_branch
from .core.actions import ACTION_CODES, action_number
from .gitutil import (output, repository_root, reset_skip_approvals,
                      set_skip_approvals)
from .handoff_selection import (HandoffSelection, resolve_handoffs,
                                SelectionKind)
from .local_ignore import ensure_runtime_ignored
from .logging_setup import LOG_FILENAME, configure, set_context
from .macros import MACRO_NAMES, execute_macro
from .migration import migrate_legacy_artifacts
from .model import Abort, Config, load_config, load_project_config
from .params_cache import save_cached_handoff
from .planner import execute_goal
from .progress import ProgressRecorder, ProgressStore, render_progress
from .sequence import execute_sequence
from .state import locked_state, read_state_snapshot
from .status import workflow_key
from .workflow import Workflow
from .zip_resume import verify_applied_zip


@dataclass(frozen=True)
class ProjectContext:
    root: Path
    config: Config
    tool_dir: Path


def _resolve_project(global_config: Config, tool_dir: Path) -> ProjectContext:
    root_name = Path(output(["git", "rev-parse", "--show-toplevel"], Path.cwd())).resolve().name
    root = repository_root(Path.cwd(), root_name)
    config = load_project_config(root, global_config)
    if config.downloads.is_relative_to(root):
        raise Abort("The downloads directory must be outside the Git repository")
    if config.applied_patches_path == config.state_path:
        raise Abort("Applied patch history must have a dedicated path")
    return ProjectContext(root, config, tool_dir)


def _select_menu_action(
    request: CliRequest, context: ProjectContext, selection: HandoffSelection,
    recorder: ProgressRecorder,
) -> CliRequest | None:
    """Dispatch read-only menu operations before acquiring a writable state lock."""
    root, config, tool_dir = context.root, context.config, context.tool_dir
    state = read_state_snapshot(config.state_path)
    preview = Workflow(root, config, selection.handoff, state,
                       force=request.mode == "force", loose=request.mode == "loose",
                       skip_previous_cycles=True, zip_selected=selection.zip_selected,
                       progress_recorder=recorder)
    chosen = preview.menu_choice()
    try:
        number = action_number(chosen)
    except ValueError as exc:
        raise Abort(str(exc)) from exc
    if number == 10:
        show_status_with_progress(root, config, state, selection.handoff,
                                  selection.handoff.patch, request.mode, recorder, tool_dir,
                                  zip_selected=selection.zip_selected)
        return None
    if number == 11:
        show_audit_with_activity(root, config, tool_dir)
        return None
    return request.with_action(ACTION_CODES[number])


def _admit_zip_start(
    request: CliRequest, context: ProjectContext, selection: HandoffSelection,
) -> tuple[bool, bool]:
    """Separate new ZIP extraction, verified resume, and legacy BRN recovery."""
    if not selection.zip_selected:
        return False, False
    if request.op in {"BAP", "2"}:
        raise Abort("2 [BAP] is deprecated for self-contained ZIPs; start with 3 [APL]")
    first = (request.op_seq.actions[0] if request.op_seq is not None
             else action_number(request.op))
    if first == 3:
        if request.op_seq is not None and not selection.sequence:
            snapshot = read_state_snapshot(context.config.state_path)
            saved = snapshot["workflows"].get(workflow_key(
                context.root, selection.handoff.branch, selection.handoff.patch))
            if isinstance(saved, dict) and saved.get("phase") not in {None, "new"}:
                verify_applied_zip(context.root, context.config, selection.handoff, snapshot)
                return False, True
        return False, False
    if first == 1:
        handoff = selection.handoff
        saved = read_state_snapshot(context.config.state_path)["workflows"].get(
            workflow_key(context.root, handoff.branch, handoff.patch), {})
        annotated = selection.with_existing_record(saved)
        if annotated.kind == SelectionKind.APPLIED_ZIP:
            recover_cache = (saved.get("zip_first") is True
                             and saved.get("phase") == "patch_applied"
                             and saved.get("applied_branch") == context.config.base
                             and saved.get("archive_sha256") == handoff.patch_sha256)
            if recover_cache:
                return True, False
        if request.op_seq is not None:
            verify_applied_zip(context.root, context.config, selection.handoff,
                               read_state_snapshot(context.config.state_path))
            return False, True
    if first not in {1, 3}:
        verify_applied_zip(context.root, context.config, selection.handoff,
                           read_state_snapshot(context.config.state_path))
        return False, True
    message = ("A newly selected self-contained ZIP must start with op=APL; "
               "BRN is only allowed to recover an already applied matching ZIP. "
               "Use op=STS or op=AUD to inspect any unfinished application")
    conflict = selection.with_conflict(message, next_step="APL")
    raise Abort(conflict.evidence)


def _execute_lifecycle(
    request: CliRequest, context: ProjectContext, selection: HandoffSelection,
    recorder: ProgressRecorder, *, menu_shown: bool, recover_cache: bool,
    resume_selected: bool,
) -> None:
    """Run exactly one workflow coordinator for normal single-handoff requests."""
    root, config, tool_dir = context.root, context.config, context.tool_dir
    handoff = selection.handoff
    if request.feature_branch is not None:
        with locked_state(config.state_path) as state:
            reassign_pending_branch(root, config, handoff, state, request.feature_branch)
    ensure_runtime_ignored(root, config.log_directory, LOG_FILENAME,
                           config.state_path, config.applied_patches_path)
    set_context(patch=handoff.patch, branch=handoff.branch, repository=handoff.repository)
    log_path = configure(config.log_directory)
    logger = logging.getLogger("apatch")
    operation_label = (request.op if request.op_seq is None
                       else ",".join(ACTION_CODES[i] for i in request.op_seq.actions))
    logger.info("invocation handoff=%s working_directory=%s mode=%s op=%s skip_approves=%s",
                selection.source_label, root, request.mode, operation_label,
                request.skip_approves)
    logger.info("repository=%s feature=%s patch=%s", root, handoff.branch, handoff.patch)
    print(f"Log: {log_path}")
    token = set_skip_approvals(request.skip_approves)
    try:
        with locked_state(config.state_path) as state:
            if resume_selected:
                evidence = verify_applied_zip(root, config, handoff, state)
                save_cached_handoff(root, handoff)
                print(f"Verified selected ZIP: {evidence.patch} | phase={evidence.phase} "
                      f"| branch={evidence.branch}; no archive replay")
            migrate_legacy_artifacts(root, tool_dir, config, state)
            show_unresolved_operations(state, root)
            workflow = Workflow(root, config, handoff, state,
                                force=request.mode == "force", loose=request.mode == "loose",
                                zip_selected=selection.zip_selected,
                                allow_followup_zip=request.followup, progress_recorder=recorder)
            if request.op_seq is not None:
                handoffs = iter(selection.sequence)

                def select_for_apply(step: int, active: Workflow) -> Workflow:
                    selected = next(handoffs)
                    if selected == active.handoff:
                        return active
                    set_context(patch=selected.patch, branch=selected.branch,
                                repository=selected.repository)
                    return Workflow(root, config, selected, state,
                                    force=request.mode == "force", loose=request.mode == "loose",
                                    zip_selected=True, allow_followup_zip=True,
                                    progress_recorder=recorder)

                execute_sequence(
                    workflow, request.op_seq,
                    select_workflow=select_for_apply if selection.sequence else None,
                    on_satisfied=(lambda action, active: active.verified_resume_step(action))
                    if resume_selected else None,
                    on_completed=lambda action, active: save_cached_handoff(root, active.handoff)
                    if active.zip_selected and
                    (action == 3 or (recover_cache and action == 1)) else None)
            else:
                result = workflow.interactive(request.op, show_header=not menu_shown)
                if (selection.zip_selected and result == "SUCCESS"
                        and (request.op in {"APL", "3"}
                             or (recover_cache and request.op in {"BRN", "1"}))):
                    save_cached_handoff(root, handoff)
    finally:
        reset_skip_approvals(token)
        recorder.flush(tool_dir)


def execute_request(request: CliRequest, tool_dir: Path) -> int:
    """Single CLI dispatcher; read-only paths never enter lifecycle bootstrap."""
    global_config = load_config(tool_dir)
    if request.info is not None:
        validate_progress_request(request)
        print(render_progress(ProgressStore(tool_dir).read_snapshot(),
                              global_limit=global_config.progress_global_limit,
                              project_limit=global_config.progress_project_limit))
        return 0
    validate_repository_request(request)
    context = _resolve_project(global_config, tool_dir)
    root, config = context.root, context.config
    if request.audit_only:
        show_audit_with_activity(root, config, tool_dir, verify_remote=request.verify_remote)
        return 0
    if request.op in MACRO_NAMES:
        execute_macro(request, root, config, tool_dir)
        return 0
    if (request.op is None and request.op_seq is None and request.handoff is None
            and not (root / ".apatch" / "params.json").exists()):
        chosen = select_without_handoff()
        if chosen == 11:
            show_audit_with_activity(root, config, tool_dir)
            return 0
        if chosen == 0:
            print("Exit selected. No action was run.")
            return 0
        if chosen != 10:
            raise Abort("Patch lifecycle actions require a selected ZIP/JSON handoff")
        request = request.with_action("STS")

    recorder = ProgressRecorder(root)
    selection = resolve_handoffs(request, config, root)
    if request.followup and not selection.zip_selected:
        raise Abort("followup=true requires a self-contained ZIP, not a legacy handoff JSON")
    if selection.handoff is not None and selection.handoff.repository != root.name:
        raise Abort("Handoff parameters belong to a different repository")
    if request.goal is not None:
        execute_goal(root, config, tool_dir, selection, goal=request.goal,
                     intent=request.intent or "auto", plan_only=request.plan_only,
                     skip_approves=request.skip_approves)
        return 0
    if request.status_only:
        show_status_with_progress(root, config, None, selection.handoff, request.patch,
                                  request.mode, recorder, tool_dir,
                                  zip_selected=selection.zip_selected)
        return 0

    menu_shown = request.op is None and request.op_seq is None
    if menu_shown:
        resolved = _select_menu_action(request, context, selection, recorder)
        if resolved is None:
            return 0
        request = resolved

    recover_cache, resume_selected = _admit_zip_start(request, context, selection)
    _execute_lifecycle(request, context, selection, recorder,
                       menu_shown=menu_shown, recover_cache=recover_cache,
                       resume_selected=resume_selected)
    return 0
