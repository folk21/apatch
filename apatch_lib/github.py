"""Guarded GitHub PR operations; no merge without live GitHub evidence."""

import json
import re

from .gitutil import confirm, head, output, remote_head, require_clean, run
from .model import Abort


def repository(config, root):
    origin = output(["git", "remote", "get-url", config.remote], root)
    match = re.fullmatch(r"(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
                         r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", origin)
    if not match:
        raise Abort("Only explicitly configured github.com Git remotes are supported")
    expected = match.group(1)
    run(["gh", "auth", "status"], root)
    resolved = output(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], root)
    if resolved.lower() != expected.lower():
        raise Abort(f"Git remote {expected} and GitHub repository {resolved} disagree")
    return resolved


def pr_list(config, root, repo, branch):
    raw = output(["gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "all",
                  "--limit", "100", "--json", "number,state,headRefName,baseRefName,headRefOid,url"], root)
    return [pr for pr in json.loads(raw) if pr["headRefName"] == branch and pr["baseRefName"] == config.base]


def pr_details(root, repo, number):
    fields = "number,state,headRefName,baseRefName,headRefOid,url,reviewDecision,mergeable,mergeStateStatus,statusCheckRollup,mergedAt"
    return json.loads(output(["gh", "pr", "view", str(number), "--repo", repo, "--json", fields], root))


def create_pr(config, handoff, root, record, save_checkpoint):
    require_clean(root)
    local = head(root)
    if remote_head(root, config, handoff.branch) != local or record.get("pushed_sha") != local:
        raise Abort("Feature branch HEAD does not match the recorded pushed SHA")
    repo = repository(config, root)
    existing = pr_list(config, root, repo, handoff.branch)
    if len(existing) > 1:
        raise Abort("Multiple matching PRs; resolve manually")
    if existing:
        pr = existing[0]
        if pr["state"] != "OPEN" or pr["headRefOid"] != local:
            raise Abort("Existing PR is closed or points to unexpected commit")
        record["phase"] = "pr_created"
        record["pr_number"] = pr["number"]
        save_checkpoint()
        print(f"Found matching PR: {pr['url']}. Run apatch again after checks/review.")
        return
    others = json.loads(output(["gh", "pr", "list", "--repo", repo, "--head", handoff.branch,
                                "--state", "open", "--json", "number,baseRefName"], root))
    if others:
        raise Abort("An open PR exists with another base branch")
    print(f"PR: {handoff.branch} -> {config.base} in {repo}")
    if not confirm("Create this pull request?"):
        return
    run(["gh", "pr", "create", "--repo", repo, "--base", config.base, "--head", handoff.branch,
         "--title", handoff.subject, "--body", handoff.message.split("\n", 1)[-1]], root)
    existing = pr_list(config, root, repo, handoff.branch)
    if len(existing) != 1 or existing[0]["state"] != "OPEN":
        raise Abort("PR created but could not be uniquely verified; inspect GitHub")
    record["phase"] = "pr_created"
    record["pr_number"] = existing[0]["number"]
    save_checkpoint()
    print("PR created. Merge is intentionally unavailable until the next invocation.")


def merge_pr(config, handoff, root, record, save_checkpoint):
    require_clean(root)
    repo = repository(config, root)
    prs = pr_list(config, root, repo, handoff.branch)
    if len(prs) != 1 or prs[0]["number"] != record.get("pr_number"):
        raise Abort("Recorded PR identity does not match GitHub")
    pr = pr_details(root, repo, record["pr_number"])
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
        run(["gh", "pr", "checks", str(pr["number"]), "--repo", repo, "--required"], root)
        for item in checks:
            result = item.get("conclusion") or item.get("state")
            if result not in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
                raise Abort(f"PR has non-successful/pending checks: {item.get('name')}: {result}")
    print(f"PR {pr['url']} | {handoff.branch} -> {config.base} | review={pr.get('reviewDecision')}")
    if not confirm("Merge this reviewed PR into the target branch?"):
        return
    run(["gh", "pr", "merge", str(pr["number"]), "--repo", repo, f"--{config.merge_method}"], root)
    latest = pr_details(root, repo, pr["number"])
    if latest["state"] != "MERGED" or not latest.get("mergedAt"):
        raise Abort("Merge command returned but GitHub does not confirm MERGED")
    record["phase"] = "merged"
    save_checkpoint()
    print("GitHub merge confirmed. Local main synchronization is a separate recoverable step.")


def sync_base(config, handoff, root, record, save_checkpoint):
    require_clean(root)
    repo = repository(config, root)
    details = pr_details(root, repo, record["pr_number"])
    if details["state"] != "MERGED":
        raise Abort("Recorded merge is not confirmed by GitHub")
    run(["git", "fetch", config.remote, config.base], root)
    local_branch = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{config.base}"], root,
                       check=False).returncode == 0
    if local_branch:
        run(["git", "switch", config.base], root)
    else:
        run(["git", "switch", "--track", "-c", config.base, f"{config.remote}/{config.base}"], root)
    run(["git", "pull", "--ff-only", config.remote, config.base], root)
    record["phase"] = "synced"
    save_checkpoint()
    print(f"Local {config.base} is synchronized after GitHub PR merge.")
