#!/usr/bin/env python3
"""Apply a project PATCH through a guarded, interactive Git workflow."""

import argparse
import logging
import sys
from pathlib import Path

from apatch_lib.gitutil import repository_root
from apatch_lib.local_ignore import ensure_log_ignored
from apatch_lib.logging_setup import LOG_FILENAME, configure, set_context
from apatch_lib.model import Abort, load_config, load_handoff, load_project_config
from apatch_lib.state import locked_state
from apatch_lib.workflow import Workflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path, help="Path to a patch handoff JSON file")
    args = parser.parse_args()
    script_dir = Path(__file__).resolve().parent
    try:
        config = load_config(script_dir)
        handoff = load_handoff(args.handoff.expanduser())
        root = repository_root(Path.cwd(), handoff.repository)
        config = load_project_config(root, config)
        if config.state_path.is_relative_to(root):
            raise Abort("The checkpoint state file must be outside the Git repository")
        if config.downloads.is_relative_to(root):
            raise Abort("The downloads directory must be outside the Git repository")
        if config.applied_patches_path.is_relative_to(root):
            raise Abort("The applied patch history must be outside the Git repository")
        if config.applied_patches_path == config.state_path:
            raise Abort("Applied patch history must have a dedicated path")
        ensure_log_ignored(root, config.log_directory, LOG_FILENAME)
        set_context(patch=handoff.patch, branch=handoff.branch, repository=handoff.repository)
        log_path = configure(config.log_directory)
        logger = logging.getLogger("apatch")
        logger.info("invocation handoff=%s working_directory=%s", args.handoff.expanduser(), root)
        logger.info("repository=%s feature=%s patch=%s", root, handoff.branch, handoff.patch)
        print(f"Log: {log_path}")
        with locked_state(config.state_path) as state:
            Workflow(root, config, handoff, state).interactive()
    except (Abort, KeyboardInterrupt, BlockingIOError) as exc:
        # Canonical-check output is logged; other subprocess output is not.
        logger = logging.getLogger("apatch")
        if logger.handlers:
            logger.warning("invocation stopped: %s",
                           str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
        print(f"STOP: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
