#!/usr/bin/env python3
"""Run producer-side checks before a separate tool builds a patch ZIP."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

from apatch_lib.artifact_preflight import preflight
from apatch_lib.model import Abort


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and verify an exact source snapshot before creating a ZIP")
    parser.add_argument("--project", type=Path, default=Path.cwd(),
                        help="Root of the source Git repository (default: current directory)")
    parser.add_argument("--prepare", action="store_true",
                        help="Explicitly run configured mutating format_commands first")
    parser.add_argument("--json", action="store_true",
                        help="Write one machine-readable result to stdout; command output goes to stderr")
    args = parser.parse_args(argv)

    error = None
    result = None
    with redirect_stdout(sys.stderr) if args.json else redirect_stdout(sys.stdout):
        try:
            result = preflight(args.project, Path(__file__).resolve().parent,
                               prepare=args.prepare)
        except Abort as exc:
            print(f"[PREFLIGHT FAILED] {exc}", file=sys.stderr, flush=True)
            error = str(exc)

    if error is not None:
        if args.json:
            print(json.dumps({"status": "failed", "error": error}))
        return 1

    assert result is not None
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True))
    else:
        print(f"[PREFLIGHT PASSED] {result.repository} {result.branch} "
              f"HEAD={result.head[:12]} paths={len(result.changed_paths)} "
              f"source_sha256={result.worktree_sha256}")
        if not args.prepare:
            print("[PREFLIGHT NOTE] No mutating preparation was requested; "
                  "only canonical read-only checks were executed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
