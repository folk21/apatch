"""Bounded, read-only Git worktree inspection with legacy runner seams."""

import hashlib
import os
from pathlib import Path

from ..mo_core.api import Abort
from .models import RepositorySnapshot, WorktreeEntry, WorktreeSnapshot


def worktree_inventory(root: Path) -> dict[str, WorktreeEntry]:
    """Inventory changed and untracked paths without reading ignored private files."""
    from .. import gitutil

    statuses = gitutil.status_paths(root)
    if not statuses:
        return {}
    raw_index = gitutil.run(["git", "--literal-pathspecs", "ls-files", "--stage", "-z",
                     "--", *sorted(statuses)], root, text=False).stdout
    index: dict[str, list[tuple[str, str, str]]] = {}
    for item in raw_index.split(b"\x00"):
        if not item:
            continue
        try:
            entry, name = item.split(b"\t", 1)
            mode, oid, stage = entry.decode("ascii").split()
        except (ValueError, UnicodeError) as exc:
            raise Abort("Malformed Git index entry during worktree inspection") from exc
        index.setdefault(os.fsdecode(name), []).append((mode, oid, stage))
    observed = {}
    for name, status in sorted(statuses.items()):
        path = root / name
        try:
            if path.is_symlink():
                observed[name] = WorktreeEntry(
                    status, tuple(sorted(index.get(name, ()))), "symlink",
                    symlink_target=os.readlink(path))
            elif path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for part in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(part)
                observed[name] = WorktreeEntry(
                    status, tuple(sorted(index.get(name, ()))), "file",
                    bytes_sha256=digest.hexdigest(),
                    executable=bool(path.stat().st_mode & 0o111))
            elif not path.exists():
                observed[name] = WorktreeEntry(
                    status, tuple(sorted(index.get(name, ()))), "missing")
            else:
                raise Abort(f"Unsupported changed path: {name!r}")
        except OSError as exc:
            raise Abort(f"Cannot inspect changed path {name!r}: {exc}") from exc
    return observed


def worktree_change_details(before: dict[str, WorktreeEntry],
                            after: dict[str, WorktreeEntry]
                            ) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Explain changed path identity without displaying project file contents."""
    result = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        if old is None:
            details = ["new changed/untracked path"]
        elif new is None:
            details = ["no longer changed"]
        else:
            details = []
            if old.status != new.status:
                details.append("Git status")
            if old.index != new.index:
                details.append("Git index entry/mode")
            if old.kind != new.kind:
                details.append("file type")
            if old.bytes_sha256 != new.bytes_sha256:
                details.append("file bytes")
            if old.executable != new.executable:
                details.append("executable bit")
            if old.symlink_target != new.symlink_target:
                details.append("symlink target")
        result.append((name, tuple(details)))
    return tuple(result)


def inspect_repository(root: Path) -> RepositorySnapshot:
    """Observe an exact root, checked-out branch, HEAD and dirty flag."""
    from .. import gitutil

    root = Path(root).resolve()
    observed = Path(gitutil.output(["git", "rev-parse", "--show-toplevel"], root)).resolve()
    if observed != root:
        raise Abort(f"Git inspection requires repository root: {observed}")
    branch = gitutil.current_branch(root)
    if not branch:
        raise Abort("Git inspection requires a checked-out named branch")
    return RepositorySnapshot(root, branch, gitutil.head(root), bool(gitutil.status_paths(root)))


def inspect_worktree(root: Path) -> WorktreeSnapshot:
    """Reject changed fingerprints or inventories observed during read-only capture."""
    from .. import gitutil

    root = Path(root).resolve()
    before_branch = gitutil.current_branch(root)
    before_head = gitutil.head(root)
    before_fingerprint, before_paths = gitutil.worktree_fingerprint(root)
    inventory = worktree_inventory(root)
    after_fingerprint, after_paths = gitutil.worktree_fingerprint(root)
    if (gitutil.current_branch(root) != before_branch
            or gitutil.head(root) != before_head
            or before_fingerprint != after_fingerprint
            or before_paths != after_paths
            or set(inventory) != set(after_paths)):
        raise Abort("Git worktree changed during read-only inspection; retry from current state")
    return WorktreeSnapshot(after_fingerprint, tuple(sorted(inventory.items())))



def index_entries(root):
    """Inspect the whole Git index, including paths entering the changed set."""
    from ..gitutil import run

    raw = run(["git", "ls-files", "--stage", "-z"], root, text=False).stdout
    entries = {}
    for item in raw.split(b"\x00"):
        if not item:
            continue
        if b"\t" not in item:
            raise Abort("FMT_INDEX_INVALID: Malformed Git index entry")
        identity, path = item.split(b"\t", 1)
        entries.setdefault(os.fsdecode(path), []).append(identity)
    return {key: tuple(sorted(value)) for key, value in entries.items()}

