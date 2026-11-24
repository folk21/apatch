"""Repository identity, branch queries, and changed-worktree fingerprinting."""

import hashlib
import os
from pathlib import Path

from ..mo_core.api import Abort


def output(argv, cwd: Path, *, timeout=None):
    from .. import gitutil
    return gitutil.run(argv, cwd, timeout=timeout).stdout.strip()


def repository_root(cwd: Path, expected_name: str):
    from .. import gitutil
    root = Path(gitutil.output(["git", "rev-parse", "--show-toplevel"], cwd)).resolve()
    if root != cwd.resolve() or root.name != expected_name:
        raise Abort(f"Run from the root of repository {expected_name!r}: {root}")
    return root


def current_branch(root):
    from .. import gitutil
    return gitutil.output(["git", "branch", "--show-current"], root)


def head(root):
    from .. import gitutil
    return gitutil.output(["git", "rev-parse", "HEAD"], root)


def is_clean(root):
    from .. import gitutil
    return not gitutil.run(["git", "status", "--porcelain", "--untracked-files=all"], root).stdout


def require_clean(root):
    from .. import gitutil
    if not gitutil.is_clean(root):
        raise Abort("Working tree is not clean; inspect git status before continuing")


def require_branch(root, branch):
    from .. import gitutil
    if gitutil.current_branch(root) != branch:
        raise Abort(f"Expected checked-out branch {branch!r}, got {gitutil.current_branch(root)!r}")


def branch_exists(root, branch):
    from .. import gitutil
    result = gitutil.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], root,
                 check=False)
    if result.returncode not in {0, 1}:
        raise Abort(f"Could not check local branch {branch!r}")
    return result.returncode == 0


def remote_head(root, config, branch):
    from .. import gitutil
    result = gitutil.run(["git", "ls-remote", "--heads", config.remote, f"refs/heads/{branch}"],
                 root, timeout=config.github_timeout_seconds)
    lines = result.stdout.splitlines()
    if not lines:
        return None
    if len(lines) != 1:
        raise Abort(f"Ambiguous remote branch lookup: {branch}")
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != f"refs/heads/{branch}" or len(fields[0]) != 40:
        raise Abort(f"Invalid remote branch response: {branch}")
    return fields[0]


def status_paths(root, *, detect_renames=True):
    """List changed paths, optionally unfolding staged renames into both endpoints."""
    args = ["git", "-c", "core.quotePath=false", "status", "--porcelain=v1",
            "--untracked-files=all", "-z"]
    if not detect_renames:
        args.append("--no-renames")
    from .. import gitutil
    data = gitutil.run(args, root, text=False).stdout
    paths = {}
    items = data.split(b"\x00")
    i = 0
    while i < len(items) and items[i]:
        line = items[i]
        name = os.fsdecode(line[3:])
        code = os.fsdecode(line[:2])
        if "R" in code or "C" in code:
            i += 1
        paths[name] = code
        i += 1
    return paths


def worktree_fingerprint(root):
    """Capture changed bytes, executable bits, and staged Git objects and modes."""
    from .. import gitutil
    paths = gitutil.status_paths(root)
    digest = hashlib.sha256()
    if paths:
        from .. import gitutil
        index = gitutil.run(["git", "ls-files", "--stage", "-z", "--", *sorted(paths)],
                    root, text=False).stdout
        digest.update(b"INDEX\x00" + index + b"\x00")
    for name, code in sorted(paths.items()):
        path = root / name
        digest.update(name.encode("utf-8", "surrogateescape") + b"\x00" + code.encode() + b"\x00")
        if path.is_symlink():
            digest.update(b"L" + os.readlink(path).encode("utf-8", "surrogateescape"))
        elif path.is_file():
            executable = bool(path.stat().st_mode & 0o111)
            digest.update(b"F\x01" if executable else b"F\x00")
            with path.open("rb") as stream:
                for part in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(part)
        elif not path.exists():
            digest.update(b"D")
        else:
            raise Abort(f"Unsupported changed path: {name}")
    return digest.hexdigest(), paths
