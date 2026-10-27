"""Read-only, bounded collectors for repository audit evidence."""

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import github
from .core.contracts import GitHubPr, StateDocument
from .created_patches import MAX_REGISTRY_BYTES, registry_path
from .model import Abort, BASENAME_PATTERN, Config
from .patch_history import MAX_HISTORY_BYTES
from .state import read_state_snapshot
from .status import _branch_present, _commit_present, local_branch, local_repository


MAX_REMOTE_PRS = 500


@dataclass(frozen=True)
class LocalAuditEvidence:
    """A snapshot of observations, without inferred workflow outcomes."""

    root: Path
    branch: str
    head: str
    dirty_count: int
    created_source: Path
    created_text: str | None
    applied_source: Path
    applied_text: str | None
    state_source: Path
    state: StateDocument
    branch_present: dict[str, bool]
    commit_present: dict[str, bool]


def safe_text(path: Path, limit: int) -> str | None:
    """Read bounded UTF-8 history without following runtime-file symlinks."""
    parent = path.parent
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
        raise Abort(f"Unsafe audit source directory: {parent}")
    if path.is_symlink():
        raise Abort(f"Audit source must not be a symlink: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Abort(f"Cannot open audit source {path}: {exc}") from exc
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise Abort(f"Audit source is not a regular file within size limit: {path}")
            raw = handle.read(limit + 1)
            if len(raw) > limit:
                raise Abort(f"Audit source exceeds size limit: {path}")
        return raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise Abort(f"Cannot read UTF-8 audit source {path}: {exc}") from exc


def local_git(root: Path, *args: str, timeout: int = 10) -> str:
    """Run local Git without optional locks or repository writes."""
    try:
        completed = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True,
            timeout=timeout, check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Abort(f"Local Git inspection failed: {args[0]}: {type(exc).__name__}") from exc
    if completed.returncode:
        raise Abort(f"Local Git inspection failed: {args[0]} (exit {completed.returncode})")
    return completed.stdout


def collect_local_evidence(root: Path, config: Config) -> LocalAuditEvidence:
    """Capture only observed filesystem, state, and local Git facts."""
    local_repository(root)
    branch = local_branch(root)
    head = local_git(root, "rev-parse", "HEAD").strip()
    dirty_count = len(local_git(root, "status", "--porcelain", "--untracked-files=all").splitlines())
    created_source = registry_path(root)
    created_text = safe_text(created_source, MAX_REGISTRY_BYTES)
    applied_source = config.applied_patches_path
    applied_text = safe_text(applied_source, MAX_HISTORY_BYTES)
    state = read_state_snapshot(config.state_path)
    repository = str(root.resolve())
    branches: dict[str, bool] = {}
    commits: dict[str, bool] = {}
    for record in state["workflows"].values():
        if not isinstance(record, dict) or record.get("repository") != repository:
            continue
        patch = record.get("patch_file")
        if not isinstance(patch, str) or not BASENAME_PATTERN.fullmatch(patch):
            continue
        actual = record.get("applied_branch") or record.get("branch")
        if isinstance(actual, str) and actual not in branches:
            branches[actual] = _branch_present(root, actual)
        commit = record.get("commit_sha")
        if isinstance(commit, str) and commit not in commits:
            commits[commit] = _commit_present(root, commit)
    return LocalAuditEvidence(
        root, branch, head, dirty_count, created_source, created_text,
        applied_source, applied_text, config.state_path, state, branches, commits,
    )


def remote_snapshot(
    config: Config, root: Path, *, git_reader: Callable[..., str] = local_git,
) -> tuple[dict[str, str], list[GitHubPr], bool]:
    """Read remote refs and bounded GitHub PR data only when explicitly requested."""
    repo = github.repository(config, root)
    raw = github.gh_output(
        config, root,
        ["gh", "pr", "list", "--repo", repo, "--state", "all", "--limit",
         str(MAX_REMOTE_PRS), "--json",
         "number,state,headRefName,baseRefName,headRefOid,mergedAt"],
    )
    prs = github.decode_pr_list(raw, expected_repo=repo, max_items=MAX_REMOTE_PRS)
    refs = git_reader(root, "ls-remote", "--heads", config.remote,
                      timeout=config.github_timeout_seconds)
    heads: dict[str, str] = {}
    for line in refs.splitlines():
        sha, sep, ref = line.partition("\t")
        if sep and re.fullmatch(r"[a-f0-9]{40}", sha) and ref.startswith("refs/heads/"):
            heads[ref.removeprefix("refs/heads/")] = sha
    return heads, prs, len(prs) < MAX_REMOTE_PRS
