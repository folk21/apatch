"""Block creation of a new feature branch while prior feature work is unfinished."""

import json
import re

from . import github
from .gitutil import current_branch, output, run
from .model import Abort


FEATURE_PREFIX = "feature/"
PR_LIMIT = 1000


def _is_github_remote(value):
    return bool(re.match(
        r"^(?:git@github\.com:|ssh://(?:[^/@]+@)?github\.com(?::\d+)?/|"
        r"https?://(?:[^/@]+@)?github\.com(?::\d+)?/)", value))


def _remote_heads(root, config):
    """Read current remote refs without writing tracking refs or fetching objects."""
    raw = output(["git", "ls-remote", "--heads", config.remote,
                  f"refs/heads/{config.base}", "refs/heads/feature/*"],
                 root, timeout=config.github_timeout_seconds)
    refs = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", parts[0]):
            raise Abort("Invalid remote branch listing; new feature branch creation blocked")
        sha, name = parts
        if name in refs:
            raise Abort("Duplicate remote branch listing; new feature branch creation blocked")
        if name == f"refs/heads/{config.base}" or name.startswith("refs/heads/feature/"):
            refs[name] = sha
        else:
            raise Abort("Unexpected remote branch listing; new feature branch creation blocked")
    base = refs.pop(f"refs/heads/{config.base}", None)
    if base is None:
        raise Abort(f"Remote base branch {config.remote}/{config.base} is unavailable; "
                    "new feature branch creation blocked")
    return base, {key.removeprefix("refs/heads/"): sha for key, sha in refs.items()}


def _local_feature_heads(root):
    raw = output(["git", "for-each-ref", "--format=%(refname:short) %(objectname)",
                  "refs/heads/feature/"], root)
    refs = {}
    for line in raw.splitlines():
        parts = line.split()
        if (len(parts) != 2 or not parts[0].startswith(FEATURE_PREFIX)
                or not re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", parts[1])):
            raise Abort("Invalid local feature branch listing; new feature branch creation blocked")
        refs[parts[0]] = parts[1]
    return refs


def _github_prs(root, config):
    repo = github.repository(config, root)
    fields = "number,state,headRefName,baseRefName,headRefOid,url"
    raw = github.gh_output(config, root, ["gh", "pr", "list", "--repo", repo,
                                         "--state", "all", "--limit", str(PR_LIMIT),
                                         "--json", fields])
    try:
        prs = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise Abort("Cannot parse GitHub PR listing; new feature branch creation blocked") from exc
    if not isinstance(prs, list) or len(prs) >= PR_LIMIT:
        raise Abort("GitHub PR listing is incomplete; new feature branch creation blocked")
    for pr in prs:
        if (not isinstance(pr, dict) or not isinstance(pr.get("headRefName"), str)
                or pr.get("state") not in {"OPEN", "CLOSED", "MERGED"}):
            raise Abort("Invalid GitHub PR listing; new feature branch creation blocked")
    return prs


def _is_ancestor_of_ref(root, sha, base_ref):
    exists = run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], root, check=False)
    if exists.returncode:
        return False
    result = run(["git", "merge-base", "--is-ancestor", sha, base_ref],
                 root, check=False)
    if result.returncode not in {0, 1}:
        raise Abort("Cannot verify feature branch ancestry; new feature branch creation blocked")
    return result.returncode == 0


def _merged_pr_at_tip(prs, branch, sha, base):
    return any(pr.get("state") == "MERGED" and pr.get("headRefName") == branch
               and pr.get("baseRefName") == base and pr.get("headRefOid") == sha
               for pr in prs)


def assert_no_unfinished_feature_branches(root, config, target, *, ignore_branch=None):
    """Fail closed on unmerged remote work or local commits before a new branch is created."""
    current = current_branch(root)
    if current.startswith(FEATURE_PREFIX) and current != target:
        dirty = output(["git", "status", "--porcelain", "--untracked-files=all"], root)
        if dirty:
            raise Abort(f"Unfinished local feature branch {current} has uncommitted changes. "
                        f"Finish it before creating {target}.")

    try:
        remote_url = output(["git", "remote", "get-url", config.remote], root)
        remote_base_sha, remote_features = _remote_heads(root, config)
        local_features = _local_feature_heads(root)
        prs = _github_prs(root, config) if _is_github_remote(remote_url) else []
    except Abort as exc:
        raise Abort("Cannot verify whether previous feature branches are finished; "
                    f"new feature branch creation blocked. Reason: {exc}") from exc

    for pr in prs:
        branch = pr["headRefName"]
        if (branch.startswith(FEATURE_PREFIX) and branch not in {target, ignore_branch}
                and pr["state"] == "OPEN"):
            raise Abort(f"сначала смерджи fb: {branch} (open PR #{pr.get('number')}: "
                        f"{pr.get('url')}).")

    for branch, sha in sorted(remote_features.items()):
        if branch in {target, ignore_branch}:
            continue
        if _merged_pr_at_tip(prs, branch, sha, config.base):
            continue
        if sha == remote_base_sha or _is_ancestor_of_ref(root, sha, remote_base_sha):
            continue
        raise Abort(f"сначала смерджи fb: {branch} (remote branch "
                    f"{config.remote}/{branch} is not confirmed merged into {config.base}).")

    for branch, sha in sorted(local_features.items()):
        if branch in {target, ignore_branch} or remote_features.get(branch) == sha:
            continue
        if (_is_ancestor_of_ref(root, sha, f"refs/heads/{config.base}")
                or _merged_pr_at_tip(prs, branch, sha, config.base)):
            continue
        commits = output(["git", "rev-list", "--count",
                          f"refs/heads/{config.base}..refs/heads/{branch}"], root)
        raise Abort(f"Unfinished local feature branch {branch} has {commits} commit(s) "
                    f"not merged into {config.base}. Finish it before creating {target}.")

    print(f"Feature branch preflight passed: no unfinished feature branches before creating {target}.")
