#!/usr/bin/env python3
"""Apply project patches with LOOSE, STRICT, or FORCE Git workflows."""

import logging
import sys
from pathlib import Path
from typing import Sequence

from apatch_lib.application import execute_request
from apatch_lib.cli_inspection import (select_without_handoff,
                                       show_audit_with_activity,
                                       show_status_with_progress,
                                       show_unresolved_operations)
from apatch_lib.cli_request import (normalize_arguments, parse_boolean,
                                    parse_operation, parse_operation_sequence,
                                    parse_request)
from apatch_lib.handoff_selection import (resolve_handoff_path,
                                          resolve_selected_handoff as _resolve_selected_handoff,
                                          resolve_sequence_zip_names)
from apatch_lib.model import Abort, Config, Handoff


__all__ = (
    "main", "parse_boolean", "normalize_arguments", "parse_operation",
    "parse_operation_sequence", "resolve_handoff_path", "resolve_selected_handoff",
    "resolve_sequence_zip_names", "show_status_with_progress",
    "show_audit_with_activity", "show_unresolved_operations", "select_without_handoff",
)


def resolve_selected_handoff(
    identifier: str | None, config: Config, root: Path
) -> tuple[Handoff, str, bool]:
    """Keep the historical helper tuple while the CLI uses typed selections."""
    selected = _resolve_selected_handoff(identifier, config, root)
    return selected.handoff, selected.source_label, selected.zip_selected


def main(argv: Sequence[str] | None = None) -> int:
    request = parse_request(argv)
    try:
        return execute_request(request, Path(__file__).resolve().parent)
    except (Abort, KeyboardInterrupt, BlockingIOError) as exc:
        logger = logging.getLogger("apatch")
        if logger.handlers:
            logger.warning("invocation stopped: %s",
                           str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
        print(f"STOP: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
