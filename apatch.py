#!/usr/bin/env python3
"""Apply project patches with LOOSE, STRICT, or FORCE Git workflows."""

import argparse
import logging
import re
import sys
from pathlib import Path

from apatch_lib.gitutil import (output, repository_root, set_skip_approvals,
                               reset_skip_approvals)
from apatch_lib.local_ignore import ensure_runtime_ignored
from apatch_lib.logging_setup import LOG_FILENAME, configure, set_context
from apatch_lib.migration import migrate_legacy_artifacts
from apatch_lib.model import Abort, BASENAME_PATTERN, load_config, load_handoff, load_project_config
from apatch_lib.params_cache import load_cached_handoff, save_cached_handoff
from apatch_lib.patch import handoff_from_zip
from apatch_lib.sequence import (OperationSequence, execute_sequence,
                                 parse_handoff_sequence, validate_multi_handoff_actions)
from apatch_lib.state import locked_state, read_state_snapshot
from apatch_lib.status import display_status, inspect_patch, select_record, workflow_key
from apatch_lib.workflow import ACTION_CODES, Workflow, action_number


def parse_boolean(value):
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise argparse.ArgumentTypeError("expected true or false")
    return normalized == "true"


def normalize_arguments(arguments):
    """Support shell-friendly key=value arguments without changing positional handoff paths."""
    normalized = []
    for argument in arguments:
        if argument.startswith("op="):
            normalized.append("--op=" + argument[len("op="):])
        elif argument.startswith("opSeq="):
            normalized.append("--op-seq=" + argument[len("opSeq="):])
        elif argument.startswith("handoffSeq="):
            normalized.append("--handoff-seq=" + argument[len("handoffSeq="):])
        elif argument.startswith("patch="):
            normalized.append("--patch=" + argument[len("patch="):])
        elif argument.startswith("skipApproves="):
            normalized.append("--skip-approves=" + argument[len("skipApproves="):])
        else:
            normalized.append(argument)
    return normalized


def parse_operation(value):
    try:
        action_number(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value.upper()


def parse_operation_sequence(value):
    try:
        return OperationSequence.parse(value, allow_multiple_apl=True)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def resolve_handoff_path(identifier: str, downloads_dir: Path) -> Path:
    """Resolve a required handoff stem under downloads, or keep an explicit path."""
    if not identifier.strip() or identifier in {".", ".."}:
        raise Abort("A handoff JSON name is required")
    candidate = Path(identifier).expanduser()
    if not candidate.name:
        raise Abort("Handoff must name a JSON file, not a directory")
    if not candidate.name.endswith(".json"):
        candidate = candidate.with_name(candidate.name + ".json")
    if candidate.parent == Path(".") and not identifier.startswith("./"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json", candidate.name):
            raise Abort("Handoff name must be a safe JSON filename")
        return downloads_dir / candidate.name
    return candidate


def resolve_selected_handoff(identifier, config, root):
    """Resolve a legacy JSON, an explicit ZIP, or verified project-local parameters."""
    if identifier is None:
        return load_cached_handoff(root), ".apatch/params.json", False
    if identifier.endswith(".json") or "/" in identifier or "\\" in identifier:
        path = resolve_handoff_path(identifier, config.downloads)
        return load_handoff(path), str(path), False
    name = identifier if identifier.endswith(".zip") else identifier + ".zip"
    if not BASENAME_PATTERN.fullmatch(name):
        raise Abort("Specify an ASCII-safe ZIP stem/basename or an explicit JSON handoff path")
    legacy = config.downloads / (identifier + ".json")
    if not identifier.endswith(".zip") and legacy.is_file() and not legacy.is_symlink():
        return load_handoff(legacy), str(legacy), False
    return handoff_from_zip(config, root, name), str(config.downloads / name), True


def resolve_sequence_zip_names(raw: str, config):
    """Select explicit ZIPs only from the configured download directory."""
    try:
        selections = parse_handoff_sequence(raw)
    except ValueError as exc:
        raise Abort(str(exc)) from exc
    names = []
    for selection in selections:
        selected = Path(selection).expanduser()
        if selected.parent != Path("."):
            if selected.suffix != ".zip" or selected.parent.resolve() != config.downloads:
                raise Abort("handoffSeq ZIP paths must resolve within configured downloads_dir")
            name = selected.name
        else:
            name = selection if selection.endswith(".zip") else selection + ".zip"
        if not BASENAME_PATTERN.fullmatch(name):
            raise Abort(f"Unsafe handoffSeq ZIP filename: {selection}")
        if name in names:
            raise Abort(f"handoffSeq repeats the same ZIP: {name}")
        names.append(name)
    return tuple(names)


def main():
    parser = argparse.ArgumentParser(
        description=("Manage project patches. LOOSE is the default mode; STRICT enforces "
                     "workflow phases; FORCE recovers from manual changes."),
        epilog=("Examples:\n"
                "  apatch.sh apatch-PATCH-2026-10-24-00-42-example op=APL skipApproves=true\n"
                "  apatch.sh apatch-PATCH-2026-10-24-00-42-example op=3\n"
                "  apatch.sh op=BRN\n"
                "  apatch.sh op=CHK\n"
                "  apatch.sh apatch-PATCH-2026-10-24-00-42-example opSeq=APL,BRN,CHK,CMT,PSH skipApproves=true\n"
                "  apatch.sh opSeq=APL,BRN,APL,CHK,CMT handoffSeq=first.zip,second.zip skipApproves=true\n"
                "  apatch.sh op=STS\n"
                "  apatch.sh strict op=CHK\n"
                "  apatch.sh force op=CMT\n"
                "  apatch.sh /path/legacy.json op=STS\n"
                "Action codes: " + ", ".join(f"{i}={code}" for i, code in enumerate(ACTION_CODES)) + "\n"
                "Select an exact ZIP stem for initial APL, or omit it for cached continuation. "
                "Explicit legacy .json paths remain supported. "
                "Without op=NUMBER, op=CODE, or opSeq=CODE,CODE, the action menu is displayed. "
                "skipApproves defaults to false and only skips confirmation prompts; "
                "Git/archive safety checks remain active."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("handoff", nargs="?", metavar="ZIP_STEM|PATH.json",
                        help="ZIP stem/basename for new APL, legacy JSON, or omit to use .apatch/params.json")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--loose", action="store_const", const="loose", dest="mode",
                       help="LOOSE (default): manual edits, shared branches, separate commit and push")
    modes.add_argument("--strict", action="store_const", const="strict", dest="mode",
                       help="STRICT: enforce workflow phases and the expected Git state")
    modes.add_argument("--force", action="store_const", const="force", dest="mode",
                       help="FORCE: reconcile manual Git operations without skipping safety checks")
    parser.set_defaults(mode="loose")
    operation_selection = parser.add_mutually_exclusive_group()
    operation_selection.add_argument("--op", type=parse_operation, metavar="NUMBER|CODE",
                                     help="Run one action by number (0-10) or code (e.g. APL, CHK, STS)")
    operation_selection.add_argument("--op-seq", "--opSeq", type=parse_operation_sequence,
                                     metavar="CODE,CODE,...",
                                     help="Run sequential actions; stop after any error or no-op; pair with skipApproves=true for unattended use")
    parser.add_argument("--handoff-seq", "--handoffSeq", metavar="ZIP1,ZIP2,...",
                        help="Explicit ZIP per APL in opSeq; multi-ZIP accumulation requires LOOSE")
    parser.add_argument("--patch", metavar="NAME.zip",
                        help="Filter read-only STS by ZIP basename")
    parser.add_argument("--skip-approves", "--skipApproves", type=parse_boolean,
                        default=False, metavar="{true,false}",
                        help="Skip interactive confirmations (default: false); does not bypass safety checks")
    args = parser.parse_args(normalize_arguments(sys.argv[1:]))
    script_dir = Path(__file__).resolve().parent
    try:
        config = load_config(script_dir)
        if args.patch is not None and not BASENAME_PATTERN.fullmatch(args.patch):
            raise Abort("--patch must be an ASCII-safe ZIP basename")
        sequence_only_status = args.op_seq is not None and args.op_seq.actions == (10,)
        status_only = args.op in {"STS", "10"} or sequence_only_status
        if args.patch is not None and not status_only:
            raise Abort("--patch is only supported for op=STS or opSeq=STS")
        root_name = Path(output(["git", "rev-parse", "--show-toplevel"], Path.cwd())).resolve().name
        root = repository_root(Path.cwd(), root_name)
        config = load_project_config(root, config)
        if config.downloads.is_relative_to(root):
            raise Abort("The downloads directory must be outside the Git repository")
        if config.applied_patches_path == config.state_path:
            raise Abort("Applied patch history must have a dedicated path")
        selected_handoffs = ()
        if args.handoff_seq is not None:
            if args.op_seq is None:
                raise Abort("handoffSeq requires opSeq; it cannot accompany op= or an interactive menu")
            names = resolve_sequence_zip_names(args.handoff_seq, config)
            try:
                validate_multi_handoff_actions(args.op_seq, names, args.mode)
            except ValueError as exc:
                raise Abort(str(exc)) from exc
            if args.op_seq.actions[0] != 3:
                raise Abort("handoffSeq requires APL as the first operation")
            if args.handoff is not None:
                positional = resolve_sequence_zip_names(args.handoff, config)
                if positional != names[:1]:
                    raise Abort("Positional ZIP selection must equal the first handoffSeq ZIP")
            selected_handoffs = tuple(handoff_from_zip(config, root, name) for name in names)
            if len({handoff.branch for handoff in selected_handoffs}) != 1:
                raise Abort("All handoffSeq ZIPs must target the same feature branch")
            handoff, source_label, zip_selected = (selected_handoffs[0],
                                                  str(config.downloads / names[0]), True)
        elif status_only and args.handoff is None and args.handoff_seq is None and not (
                (root / ".apatch" / "params.json").exists()
                or (root / ".apatch" / "params.json").is_symlink()):
            handoff, source_label, zip_selected = None, "stored workflow", False
        else:
            if args.op_seq is not None and sum(action in {2, 3} for action in args.op_seq.actions) > 1:
                raise Abort("Multiple APL actions require explicit handoffSeq ZIP selections")
            handoff, source_label, zip_selected = resolve_selected_handoff(args.handoff, config, root)
        if handoff is not None and handoff.repository != root.name:
            raise Abort("Handoff parameters belong to a different repository")
        if status_only:
            state = read_state_snapshot(config.state_path)
            record, patch, planned = select_record(root, state, handoff, patch=args.patch)
            display_status(inspect_patch(root, config, record, patch, planned, args.mode))
            return 0
        menu_shown = args.op is None and args.op_seq is None
        if menu_shown:
            state = read_state_snapshot(config.state_path)
            preview = Workflow(root, config, handoff, state,
                               force=args.mode == "force", loose=args.mode == "loose",
                               skip_previous_cycles=True, zip_selected=zip_selected)
            selection = preview.menu_choice()
            try:
                action = action_number(selection)
            except ValueError as exc:
                raise Abort(str(exc)) from exc
            if action == 10:
                display_status(inspect_patch(root, config, preview.record, handoff.patch,
                                             handoff.branch, args.mode))
                return 0
            args.op = ACTION_CODES[action]
        recover_cache = False
        if zip_selected:
            if args.op in {"BAP", "2"}:
                raise Abort("2 [BAP] is deprecated for self-contained ZIPs; start with 3 [APL]")
            first = args.op_seq.actions[0] if args.op_seq is not None else action_number(args.op)
            if first != 3:
                if first == 1:
                    saved = read_state_snapshot(config.state_path)["workflows"].get(
                        workflow_key(root, handoff.branch, handoff.patch), {})
                    recover_cache = (saved.get("zip_first") is True
                                     and saved.get("phase") == "patch_applied"
                                     and saved.get("applied_branch") == config.base
                                     and saved.get("archive_sha256") == handoff.patch_sha256)
                if not recover_cache:
                    raise Abort("A newly selected self-contained ZIP must start with op=APL; "
                                "BRN is only allowed to recover an already applied matching ZIP")
        ensure_runtime_ignored(root, config.log_directory, LOG_FILENAME,
                               config.state_path, config.applied_patches_path)
        set_context(patch=handoff.patch, branch=handoff.branch, repository=handoff.repository)
        log_path = configure(config.log_directory)
        logger = logging.getLogger("apatch")
        logger.info("invocation handoff=%s working_directory=%s mode=%s op=%s skip_approves=%s",
                    source_label, root, args.mode,
                    args.op if args.op_seq is None else ",".join(ACTION_CODES[i] for i in args.op_seq.actions),
                    args.skip_approves)
        logger.info("repository=%s feature=%s patch=%s", root, handoff.branch, handoff.patch)
        print(f"Log: {log_path}")
        token = set_skip_approvals(args.skip_approves)
        try:
            with locked_state(config.state_path) as state:
                migrate_legacy_artifacts(root, script_dir, config, state)
                workflow = Workflow(root, config, handoff, state,
                                    force=args.mode == "force", loose=args.mode == "loose",
                                    zip_selected=zip_selected)
                if args.op_seq is not None:
                    selections = iter(selected_handoffs)

                    def select_for_apply(step, active):
                        selected = next(selections)
                        if selected == active.handoff:
                            return active
                        set_context(patch=selected.patch, branch=selected.branch,
                                    repository=selected.repository)
                        return Workflow(root, config, selected, state,
                                        force=args.mode == "force", loose=args.mode == "loose",
                                        zip_selected=True, allow_followup_zip=True)

                    execute_sequence(workflow, args.op_seq,
                                     select_workflow=select_for_apply if selected_handoffs else None,
                                     on_completed=lambda action, active: save_cached_handoff(root, active.handoff)
                                     if active.zip_selected and (action == 3 or (recover_cache and action == 1)) else None)
                else:
                    result = workflow.interactive(args.op, show_header=not menu_shown)
                    if zip_selected and result == "SUCCESS" and (args.op in {"APL", "3"}
                                                                   or (recover_cache and args.op in {"BRN", "1"})):
                        save_cached_handoff(root, handoff)
        finally:
            reset_skip_approvals(token)
    except (Abort, KeyboardInterrupt, BlockingIOError) as exc:
        # Only failed canonical checks retain a bounded diagnostic output tail.
        logger = logging.getLogger("apatch")
        if logger.handlers:
            logger.warning("invocation stopped: %s",
                           str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
        print(f"STOP: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
