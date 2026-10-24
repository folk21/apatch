"""Guarded GitHub PR operations; no merge without live GitHub evidence."""

import json
import re

from .gitutil import confirm, head, output, remote_head, require_clean, run
from .model import Abort


def gh_run(config, root, argv):
    """Bound every GitHub CLI call without shortening project verification commands."""
    return run(argv, root, timeout=config.github_timeout_seconds)


def gh_output(config, root, argv):
    return output(argv, root, timeout=config.github_timeout_seconds)


def repository(config, root):
    expected = remote_repository(config, root)
    gh_run(config, root, ["gh", "auth", "status"])
    resolved = gh_output(config, root, ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    if resolved.lower() != expected.lower():
        raise Abort(f"Git remote {expected} and GitHub repository {resolved} disagree")
    return resolved


def remote_repository(config, root):
    """Read the repository identity from Git without contacting the GitHub API."""
    origin = output(["git", "remote", "get-url", config.remote], root)
    match = re.fullmatch(r"(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
                         r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", origin)
    if not match:
        raise Abort("Only explicitly configured github.com Git remotes are supported")
    return match.group(1)


def pr_list(config, root, repo, branch, *, include_other_bases=False):
    raw = gh_output(config, root, ["gh", "pr", "list", "--repo", repo, "--head", branch,
                                   "--state", "all", "--limit", "100", "--json",
                                   "number,state,headRefName,baseRefName,headRefOid,url"])
    matches = [pr for pr in json.loads(raw) if pr["headRefName"] == branch]
    return matches if include_other_bases else [pr for pr in matches if pr["baseRefName"] == config.base]


def pr_details(config, root, repo, number):
    fields = "number,state,headRefName,baseRefName,headRefOid,url,reviewDecision,mergeable,mergeStateStatus,statusCheckRollup,mergedAt"
    return json.loads(gh_output(config, root, ["gh", "pr", "view", str(number), "--repo", repo, "--json", fields]))


def create_pr(config, handoff, root, record, save_checkpoint):
    require_clean(root)
    local = head(root)
    if remote_head(root, config, handoff.branch) != local or record.get("pushed_sha") != local:
        raise Abort("Feature branch HEAD does not match the recorded pushed SHA")
    repo = repository(config, root)
    print(f"Searching for existing PRs from {handoff.branch} in {repo} (GitHub timeout: "
          f"{config.github_timeout_seconds}s)...")
    prs = pr_list(config, root, repo, handoff.branch, include_other_bases=True)
    existing = [pr for pr in prs if pr["baseRefName"] == config.base]
    if len(existing) > 1:
        raise Abort("Multiple matching PRs; resolve manually")
    if any(pr["state"] == "OPEN" and pr["baseRefName"] != config.base for pr in prs):
        raise Abort("An open PR exists with another base branch")
    if existing:
        pr = existing[0]
        if pr["state"] != "OPEN" or pr["headRefOid"] != local:
            raise Abort("Existing PR is closed or points to unexpected commit")
        record["phase"] = "pr_created"
        record["pr_number"] = pr["number"]
        save_checkpoint()
        print(f"Found matching PR: {pr['url']}. Run apatch again after checks/review.")
        return
    print(f"PR: {handoff.branch} -> {config.base} in {repo}")
    if not confirm("Create this pull request?"):
        return
    print("Creating GitHub PR. If the network times out, retry op=PR to find it safely.")
    gh_run(config, root, ["gh", "pr", "create", "--repo", repo, "--base", config.base,
                          "--head", handoff.branch, "--title", handoff.subject,
                          "--body", handoff.message.split("\n", 1)[-1]])
    print("PR creation request completed; verifying the PR on GitHub...")
    existing = pr_list(config, root, repo, handoff.branch)
    if len(existing) != 1 or existing[0]["state"] != "OPEN":
        raise Abort("PR created but could not be uniquely verified; inspect GitHub")
    record["phase"] = "pr_created"
    record["pr_number"] = existing[0]["number"]
    save_checkpoint()
    print("PR created. Merge is intentionally unavailable until the next invocation.")


def merge_pr(config, handoff, root, record, save_checkpoint):
    approval = "required" if config.require_approval else "not required"
    print(f"PR review approval: {approval} (source: {config.review_approval_source}).")
    checks = "required" if config.require_checks else "not required"
    print(f"PR CI checks: {checks} (source: {config.required_checks_source}).")
    require_clean(root)
    repo = repository(config, root)
    prs = pr_list(config, root, repo, handoff.branch)
    if len(prs) != 1 or prs[0]["number"] != record.get("pr_number"):
        raise Abort("Recorded PR identity does not match GitHub")
    pr = pr_details(config, root, repo, record["pr_number"])
    if (pr["state"] != "OPEN" or pr["baseRefName"] != config.base
            or pr["headRefName"] != handoff.branch
            or pr["headRefOid"] != record.get("pushed_sha")
            or remote_head(root, config, handoff.branch) != record.get("pushed_sha")):
        raise Abort("PR or remote ref has drifted")
    if pr["mergeable"] != "MERGEABLE" or pr["mergeStateStatus"] != "CLEAN":
        raise Abort(f"PR is not cleanly mergeable: {pr['mergeable']}/{pr['mergeStateStatus']}")
    if config.require_approval and pr.get("reviewDecision") != "APPROVED":
        raise Abort(f"PR review not approved: {pr.get('reviewDecision')}")
    if config.require_checks:
        checks = pr.get("statusCheckRollup") or []
        if not checks:
            raise Abort("PR has no published checks; refusing to assume CI passed")
        gh_run(config, root, ["gh", "pr", "checks", str(pr["number"]), "--repo", repo, "--required"])
        for item in checks:
            result = item.get("conclusion") or item.get("state")
            if result not in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
                raise Abort(f"PR has non-successful/pending checks: {item.get('name')}: {result}")
    print(f"PR {pr['url']} | {handoff.branch} -> {config.base} | review={pr.get('reviewDecision')}")
    if not confirm("Merge this PR into the target branch?"):
        return
    gh_run(config, root, ["gh", "pr", "merge", str(pr["number"]), "--repo", repo, f"--{config.merge_method}"])
    latest = pr_details(config, root, repo, pr["number"])
    if latest["state"] != "MERGED" or not latest.get("mergedAt"):
        raise Abort("Merge command returned but GitHub does not confirm MERGED")
    record["phase"] = "merged"
    save_checkpoint()
    print("GitHub merge confirmed. Local main synchronization is a separate recoverable step.")


def sync_local_base(config, root):
    """Synchronize the configured base branch using Git, independently of PR state."""
    require_clean(root)
    local_branch = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{config.base}"], root,
                       check=False).returncode == 0
    if local_branch:
        run(["git", "switch", config.base], root)
        try:
            run(["git", "pull", "--ff-only", config.remote, config.base], root)
        except Abort:
            print(f"WARNING: Switched to {config.base}, but remote synchronization is incomplete.")
            raise
    else:
        run(["git", "fetch", "--no-tags", config.remote,
             f"refs/heads/{config.base}:refs/remotes/{config.remote}/{config.base}"], root)
        run(["git", "switch", "--track", "-c", config.base, f"{config.remote}/{config.base}"], root)
    print(f"Local {config.base} synchronized with {config.remote}/{config.base}.")
    return head(root)


def confirmed_merged_pr(config, handoff, root, record):
    """Check merge status via one GitHub query without performing Git operations."""
    repo = remote_repository(config, root)
    merged = [pr for pr in pr_list(config, root, repo, handoff.branch) if pr["state"] == "MERGED"]
    if len(merged) != 1:
        raise Abort("GitHub has not confirmed exactly one merged PR for this feature branch")
    pr = merged[0]
    if record.get("pr_number") is not None and record["pr_number"] != pr["number"]:
        raise Abort("Merged PR differs from the recorded PR number")
    if record.get("pushed_sha") and record["pushed_sha"] != pr["headRefOid"]:
        raise Abort("Merged PR points to a different feature branch revision")
    return pr


def sync_base(config, handoff, root, record, save_checkpoint):
    require_clean(root)
    repo = repository(config, root)
    details = pr_details(config, root, repo, record["pr_number"])
    if details["state"] != "MERGED":
        raise Abort("Recorded merge is not confirmed by GitHub")
    record["local_base_head"] = sync_local_base(config, root)
    record["phase"] = "synced"
    save_checkpoint()
    print(f"Local {config.base} is synchronized after GitHub PR merge.")
