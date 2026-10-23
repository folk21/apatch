#!/usr/bin/env python3
"""Apply project patches with LOOSE, STRICT, or FORCE Git workflows."""

import argparse
import logging
import sys
from pathlib import Path

from apatch_lib.gitutil import repository_root, set_skip_approvals, reset_skip_approvals
from apatch_lib.local_ignore import ensure_runtime_ignored
from apatch_lib.logging_setup import LOG_FILENAME, configure, set_context
from apatch_lib.migration import migrate_legacy_artifacts
from apatch_lib.model import Abort, load_config, load_handoff, load_project_config
from apatch_lib.state import locked_state
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


def main():
    parser = argparse.ArgumentParser(
        description=("Manage project patches. LOOSE is the default mode; STRICT enforces "
                     "workflow phases; FORCE recovers from manual changes."),
        epilog=("Examples:\n"
                "  apatch.sh op=3 skipApproves=true\n"
                "  apatch.sh op=APL skipApproves=true\n"
                "  apatch.sh strict op=4\n"
                "  apatch.sh strict op=CHK\n"
                "  apatch.sh force op=5 skipApproves=true\n"
                "Action codes: " + ", ".join(f"{i}={code}" for i, code in enumerate(ACTION_CODES)) + "\n"
                "Without op=NUMBER or op=CODE, the numbered action menu is displayed. "
                "skipApproves defaults to false and only skips confirmation prompts; "
                "Git/archive safety checks remain active."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("handoff", nargs="?", type=Path,
                        help="Path to a patch handoff JSON file (default: ~/Downloads/<project>_patch_params.json)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--loose", action="store_const", const="loose", dest="mode",
                       help="LOOSE (default): manual edits, shared branches, separate commit and push")
    modes.add_argument("--strict", action="store_const", const="strict", dest="mode",
                       help="STRICT: enforce workflow phases and the expected Git state")
    modes.add_argument("--force", action="store_const", const="force", dest="mode",
                       help="FORCE: reconcile manual Git operations without skipping safety checks")
    parser.set_defaults(mode="loose")
    parser.add_argument("--op", type=parse_operation, metavar="NUMBER|CODE",
                        help="Run an action directly by number (0-9) or uppercase code (e.g. APL, CHK, PR)")
    parser.add_argument("--skip-approves", "--skipApproves", type=parse_boolean,
                        default=False, metavar="{true,false}",
                        help="Skip interactive confirmations (default: false); does not bypass safety checks")
    args = parser.parse_args(normalize_arguments(sys.argv[1:]))
    handoff_path = (args.handoff if args.handoff is not None else
                    Path.home() / "Downloads" / f"{Path.cwd().resolve().name}_patch_params.json")
    script_dir = Path(__file__).resolve().parent
    try:
        config = load_config(script_dir)
        handoff = load_handoff(handoff_path.expanduser())
        root = repository_root(Path.cwd(), handoff.repository)
        config = load_project_config(root, config)
        if config.downloads.is_relative_to(root):
            raise Abort("The downloads directory must be outside the Git repository")
        if config.applied_patches_path == config.state_path:
            raise Abort("Applied patch history must have a dedicated path")
        ensure_runtime_ignored(root, config.log_directory, LOG_FILENAME,
                               config.state_path, config.applied_patches_path)
        set_context(patch=handoff.patch, branch=handoff.branch, repository=handoff.repository)
        log_path = configure(config.log_directory)
        logger = logging.getLogger("apatch")
        logger.info("invocation handoff=%s working_directory=%s mode=%s op=%s skip_approves=%s",
                    handoff_path.expanduser(), root, args.mode, args.op, args.skip_approves)
        logger.info("repository=%s feature=%s patch=%s", root, handoff.branch, handoff.patch)
        print(f"Log: {log_path}")
        token = set_skip_approvals(args.skip_approves)
        try:
            with locked_state(config.state_path) as state:
                migrate_legacy_artifacts(root, script_dir, config, state)
                Workflow(root, config, handoff, state,
                         force=args.mode == "force", loose=args.mode == "loose").interactive(args.op)
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
