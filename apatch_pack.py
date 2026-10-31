#!/usr/bin/env python3
"""Verify a source repository and produce a self-contained patch ZIP."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

from apatch_lib.artifact_packaging import pack_source
from apatch_lib.model import Abort


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run project preflight and package only explicitly selected source paths")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--branch", required=True, help="Destination feature branch")
    parser.add_argument("--message", required=True, help="Commit message for the handoff")
    parser.add_argument("--include", action="append", default=[], metavar="PATH",
                        help="Changed/new source file to package; repeat for each file")
    parser.add_argument("--delete", action="append", default=[], metavar="PATH",
                        help="Deleted tracked source path; repeat for each file")
    parser.add_argument("--base-commit", default=None,
                        help="Optional exact destination base commit SHA")
    parser.add_argument("--prepare", action="store_true",
                        help="Run configured mutating formatters before checks")
    parser.add_argument("--json", action="store_true",
                        help="Emit one JSON result on stdout; stream check logs to stderr")
    args = parser.parse_args(argv)

    error = None
    result = None
    with redirect_stdout(sys.stderr) if args.json else redirect_stdout(sys.stdout):
        try:
            result = pack_source(args.project, Path(__file__).resolve().parent,
                                 args.output, branch=args.branch, message=args.message,
                                 included=tuple(args.include), deleted=tuple(args.delete),
                                 prepare=args.prepare, base_commit=args.base_commit)
        except Abort as exc:
            error = str(exc)
            print(f"[PACKAGING FAILED] {exc}", file=sys.stderr, flush=True)
    if error is not None:
        if args.json:
            print(json.dumps({"status": "failed", "error": error}))
        return 1

    assert result is not None
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True))
    else:
        print(f"[PACKAGING PASSED] {result.output} SHA256={result.zip_sha256} "
              f"files={len(result.files)} deletions={len(result.deleted_paths)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
