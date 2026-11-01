#!/usr/bin/env python3
"""Verify a source repository and produce a self-contained patch ZIP."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

from apatch_lib.artifact_packaging import discover_source_paths, pack_source
from apatch_lib.help_reference import PACK_HELP_EPILOG
from apatch_lib.model import Abort


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Review changed source paths or run preflight and build a verified ZIP",
        epilog=PACK_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, default=Path.cwd(),
                        help="Source Git repository root (default: current directory)")
    parser.add_argument("--discover", action="store_true",
                        help="READ-ONLY: list Git-changed/new/deleted files and suggested flags")
    parser.add_argument("--output", type=Path,
                        help="Destination ZIP outside source repository; must not exist")
    parser.add_argument("--branch", help="Target feature branch (feature/NAME)")
    parser.add_argument("--message", help="Commit message embedded in the ZIP handoff")
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

    if args.discover:
        if (args.output is not None or args.branch is not None or args.message is not None
                or args.include or args.delete or args.base_commit is not None or args.prepare):
            parser.error("--discover cannot be combined with ZIP publishing options")
        try:
            with redirect_stdout(sys.stderr) if args.json else redirect_stdout(sys.stdout):
                candidates = discover_source_paths(args.project)
        except Abort as exc:
            if args.json:
                print(json.dumps({"status": "failed", "error": str(exc)}))
            else:
                print(f"[DISCOVERY FAILED] {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(candidates.to_dict(), sort_keys=True))
        else:
            print(f"[DISCOVERY] {candidates.repository} {candidates.branch} "
                  f"HEAD={candidates.head[:12]}")
            if candidates.include or candidates.delete:
                print("Suggested explicit packaging arguments:")
                print("  " + candidates.suggested_flags())
                if candidates.untracked:
                    print("Review untracked files before including them: "
                          + ", ".join(repr(name) for name in candidates.untracked))
            else:
                print("No changed or untracked source files were found.")
            print("Discovery is read-only and does not approve or package any file.")
        return 0

    if args.output is None or args.branch is None or args.message is None:
        parser.error("packaging requires --output, --branch, and --message; "
                     "use --discover to inspect source paths first")

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
