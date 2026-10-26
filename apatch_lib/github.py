"""Guarded GitHub PR operations; no merge without live GitHub evidence."""

import json
import re
import time
from pathlib import Path
from typing import cast

from .core.contracts import GitHubPr
from .gitutil import confirm, head, output, remote_head, require_clean, run
from .model import Abort, Config, RemoteOutcomeUnknown


_TRANSIENT_GITHUB_ERROR = re.compile(
    r"i/o timeout|timed out|timeout|connection reset by peer|"
    r"connection refused|temporary failure in name resolution|"
    r"could not resolve host|no such host|TLS handshake timeout|"
    r"(?:HTTP |status code )(?:502|503|504)\b",
    re.IGNORECASE,
)
_READ_RETRY_DELAY_SECONDS = 0.5
_MAX_GITHUB_JSON_BYTES = 8 * 1024 * 1024
_MAX_GITHUB_PRS = 500
_PR_STATES = frozenset({"OPEN", "CLOSED", "MERGED"})


def _github_json(raw: str, source: str) -> object:
    """Decode bounded, untrusted CLI output without including its body in errors."""
    try:
        size = len(raw.encode("utf-8")) if type(raw) is str else _MAX_GITHUB_JSON_BYTES + 1
    except UnicodeError as exc:
        raise Abort(f"Invalid {source}: malformed UTF-8 text") from exc
    if size > _MAX_GITHUB_JSON_BYTES:
        raise Abort(f"Invalid {source}: response is not bounded UTF-8 JSON")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Abort(f"Invalid {source}: malformed JSON") from exc


def _validate_pr(value: object, source: str, *, require_url: bool,
                 expected_repo: str | None) -> GitHubPr:
    if not isinstance(value, dict):
        raise Abort(f"Invalid {source}: PR entry must be an object")
    number = value.get("number")
    if type(number) is not int or not 0 < number <= 2**63 - 1:
        raise Abort(f"Invalid {source}: number must be a positive integer")
    if type(value.get("state")) is not str or value["state"] not in _PR_STATES:
        raise Abort(f"Invalid {source}: state must be OPEN, CLOSED or MERGED")
    for field in ("headRefName", "baseRefName"):
        name = value.get(field)
        if (type(name) is not str or not name or len(name) > 255
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise Abort(f"Invalid {source}: {field} must be a bounded branch name")
    oid = value.get("headRefOid")
    if oid is not None and (type(oid) is not str or re.fullmatch(r"[a-f0-9]{40}", oid) is None):
        raise Abort(f"Invalid {source}: headRefOid must be a Git SHA or null")
    if "url" in value or require_url:
        url = value.get("url")
        if (type(url) is not str or len(url) > 2048
                or any(ord(char) < 32 or ord(char) == 127 for char in url)
                or not url.startswith("https://github.com/")):
            raise Abort(f"Invalid {source}: URL must be a GitHub HTTPS URL")
        if expected_repo is not None:
            match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/pull/([1-9][0-9]*)", url)
            if (match is None or match.group(1).lower() != expected_repo.lower()
                    or int(match.group(2)) != number):
                raise Abort(f"Invalid {source}: PR URL does not match the selected repository")
    for field in ("mergedAt", "reviewDecision", "mergeable", "mergeStateStatus"):
        if field in value and value[field] is not None and (
                type(value[field]) is not str or len(value[field]) > 256):
            raise Abort(f"Invalid {source}: {field} must be a string or null")
    if "statusCheckRollup" in value and value["statusCheckRollup"] is not None:
        checks = value["statusCheckRollup"]
        if not isinstance(checks, list) or len(checks) > 500:
            raise Abort(f"Invalid {source}: statusCheckRollup must be a bounded list")
        for check in checks:
            if not isinstance(check, dict):
                raise Abort(f"Invalid {source}: statusCheckRollup entries must be objects")
            for field in ("name", "context", "state", "conclusion"):
                if field in check and check[field] is not None and (
                        type(check[field]) is not str or len(check[field]) > 256):
                    raise Abort(f"Invalid {source}: check {field} must be a string or null")
    return cast(GitHubPr, value)


def decode_pr_list(raw: str, *, expected_repo: str | None = None,
                   require_url: bool = False, max_items: int = _MAX_GITHUB_PRS) -> list[GitHubPr]:
    """Parse PR list responses, including the narrower read-only audit shape."""
    value = _github_json(raw, "GitHub PR list")
    if not isinstance(value, list) or len(value) > max_items:
        raise Abort("Invalid GitHub PR list: expected a bounded list")
    return [_validate_pr(item, "GitHub PR list", require_url=require_url,
                         expected_repo=expected_repo) for item in value]


def decode_pr_details(raw: str, *, expected_repo: str | None = None) -> GitHubPr:
    """Parse a PR detail object before merge policy evaluates its evidence."""
    value = _github_json(raw, "GitHub PR details")
    pr = _validate_pr(value, "GitHub PR details", require_url=True,
                      expected_repo=expected_repo)
    for field in ("mergeable", "mergeStateStatus"):
        if field not in pr:
            raise Abort(f"Invalid GitHub PR details: missing {field}")
    return pr


def _github_read(config, root, argv, *, capture_output):
    """Retry transient failures only for explicitly read-only GitHub commands."""
    executor = output if capture_output else run
    for attempt in range(2):
        try:
            return executor(argv, root, timeout=config.github_timeout_seconds)
        except Abort as exc:
            if attempt or not _TRANSIENT_GITHUB_ERROR.search(str(exc)):
                raise
            print(f"WARNING: GitHub read timed out or failed transiently; retrying once "
                  f"after {_READ_RETRY_DELAY_SECONDS}s: {' '.join(argv[:3])}")
            time.sleep(_READ_RETRY_DELAY_SECONDS)
    raise AssertionError("Unreachable GitHub retry state")


def gh_run(config, root, argv):
    """Bound every GitHub CLI call without shortening project verification commands."""
    if argv[:3] in (["gh", "auth", "status"], ["gh", "pr", "checks"]):
        return _github_read(config, root, argv, capture_output=False)
    try:
        return run(argv, root, timeout=config.github_timeout_seconds)
    except Abort as exc:
        if (argv[:3] in (["gh", "pr", "create"], ["gh", "pr", "merge"])
                and _TRANSIENT_GITHUB_ERROR.search(str(exc))):
            raise RemoteOutcomeUnknown(
                f"GitHub PR {argv[2]} result is unknown after a transport failure: {exc}. "
                "Check live PR status before a manual reconciliation; no automatic retry was attempted."
            ) from exc
        raise


def gh_output(config, root, argv):
    if argv[:3] in (["gh", "repo", "view"], ["gh", "pr", "list"],
                    ["gh", "pr", "view"]):
        return _github_read(config, root, argv, capture_output=True)
    return output(argv, root, timeout=config.github_timeout_seconds)


def repository(config, root):
    expected = remote_repository(config, root)
    gh_run(config, root, ["gh", "auth", "status"])
    resolved = gh_output(config, root, ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    if resolved.lower() != expected.lower():
        raise Abort(f"Git remote {expected} and GitHub repository {resolved} disagree")
    return resolved


def verified_repository(config, root, already_verified=None):
    """Reuse a verified repository identity while rechecking the local Git remote."""
    if already_verified is None:
        return repository(config, root)
    current = remote_repository(config, root)
    if current.lower() != already_verified.lower():
        raise Abort(f"Git remote {current} changed after verifying GitHub repository "
                    f"{already_verified}")
    return already_verified


def remote_repository(config, root):
    """Read the repository identity from Git without contacting the GitHub API."""
    origin = output(["git", "remote", "get-url", config.remote], root)
    match = re.fullmatch(r"(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
                         r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", origin)
    if not match:
        raise Abort("Only explicitly configured github.com Git remotes are supported")
    return match.group(1)


def pr_list(config: Config, root: Path, repo: str, branch: str, *,
            include_other_bases: bool = False) -> list[GitHubPr]:
    raw = gh_output(config, root, ["gh", "pr", "list", "--repo", repo, "--head", branch,
                                   "--state", "all", "--limit", "100", "--json",
                                   "number,state,headRefName,baseRefName,headRefOid,url,mergedAt"])
    matches = [pr for pr in decode_pr_list(raw, expected_repo=repo, require_url=True,
                                          max_items=100) if pr["headRefName"] == branch]
    return matches if include_other_bases else [pr for pr in matches if pr["baseRefName"] == config.base]


def pr_details(config: Config, root: Path, repo: str, number: int) -> GitHubPr:
    fields = "number,state,headRefName,baseRefName,headRefOid,url,reviewDecision,mergeable,mergeStateStatus,statusCheckRollup,mergedAt"
    raw = gh_output(config, root, ["gh", "pr", "view", str(number), "--repo", repo,
                                   "--json", fields])
    pr = decode_pr_details(raw, expected_repo=repo)
    if pr["number"] != number:
        raise Abort("Invalid GitHub PR details: returned PR number differs from requested PR")
    return pr


def assert_pr_matches_revision(config, handoff, pr, sha, *, merged=False):
    """Require an exact PR identity and revision, including for previously merged PRs."""
    if not sha:
        raise Abort("Cannot verify the current patch's pushed commit; PR recovery is blocked")
    if (pr.get("headRefName") != handoff.branch
            or pr.get("baseRefName") != config.base
            or pr.get("headRefOid") != sha):
        number = pr.get("number", "unknown")
        label = "Merged" if merged else "Selected"
        raise Abort(f"{label} PR #{number} does not contain the current patch revision {sha}. "
                    "An older PR cannot complete the current workflow; create or select a PR "
                    "for the currently pushed commit.")


def _record_current_pr(record, pr):
    previous_number = record.get("pr_number")
    if previous_number is not None and previous_number != pr["number"]:
        print(f"Reconciled current patch with PR #{pr['number']} instead of historical "
              f"PR #{previous_number}; previous merge/sync evidence is not reused.")
        record.pop("local_base_head", None)
    record["phase"] = "pr_created"
    record["pr_number"] = pr["number"]


def create_pr(config, handoff, root, record, save_checkpoint):
    require_clean(root)
    local = head(root)
    if remote_head(root, config, handoff.branch) != local or record.get("pushed_sha") != local:
        raise Abort("Feature branch HEAD does not match the recorded pushed SHA")
    repo = repository(config, root)
    print(f"Searching for existing PRs from {handoff.branch} in {repo} (GitHub timeout: "
          f"{config.github_timeout_seconds}s)...")
    prs = pr_list(config, root, repo, handoff.branch, include_other_bases=True)
    active = [pr for pr in prs if pr["state"] == "OPEN"]
    if any(pr["baseRefName"] != config.base for pr in active):
        raise Abort("An open PR exists with another base branch")
    if len(active) > 1:
        raise Abort("Multiple open PRs exist for this feature branch; resolve manually")
    if active:
        pr = active[0]
        assert_pr_matches_revision(config, handoff, pr, local)
        _record_current_pr(record, pr)
        save_checkpoint()
        print(f"Found matching PR: {pr['url']}. Run apatch again after checks/review.")
        return
    same_revision = [pr for pr in prs if (pr["baseRefName"] == config.base
                                           and pr["headRefOid"] == local)]
    if same_revision:
        numbers = ", ".join(f"#{pr['number']} ({pr['state']})" for pr in same_revision)
        raise Abort(f"Current commit {local} already has a closed or merged PR: {numbers}. "
                    "Inspect GitHub before attempting a new PR for the same revision.")
    historical = [pr for pr in prs if pr["baseRefName"] == config.base]
    if historical:
        print("Historical PRs exist for this branch, but none includes the current pushed "
              "commit. A separate PR is required for the new revision.")
    print(f"PR: {handoff.branch} -> {config.base} in {repo}")
    if not confirm("Create this pull request?"):
        return
    print("Creating GitHub PR. If the network times out, retry op=PR to find it safely.")
    gh_run(config, root, ["gh", "pr", "create", "--repo", repo, "--base", config.base,
                          "--head", handoff.branch, "--title", handoff.subject,
                          "--body", handoff.message.split("\n", 1)[-1]])
    print("PR creation request completed; verifying the PR on GitHub...")
    try:
        active_after_create = [pr for pr in pr_list(config, root, repo, handoff.branch)
                               if pr["state"] == "OPEN"]
    except Abort as exc:
        raise RemoteOutcomeUnknown(
            f"PR creation command returned, but GitHub verification was unavailable: {exc}. "
            "Inspect the live PR list before retrying."
        ) from exc
    if len(active_after_create) != 1:
        raise RemoteOutcomeUnknown("PR creation command returned, but no unique matching open PR "
                                   "was confirmed; inspect GitHub before retrying")
    assert_pr_matches_revision(config, handoff, active_after_create[0], local)
    _record_current_pr(record, active_after_create[0])
    save_checkpoint()
    print("PR created. Merge is intentionally unavailable until the next invocation.")


def merge_pr(config, handoff, root, record, save_checkpoint, *, verified_repo=None):
    approval = "required" if config.require_approval else "not required"
    print(f"PR review approval: {approval} (source: {config.review_approval_source}).")
    checks = "required" if config.require_checks else "not required"
    print(f"PR CI checks: {checks} (source: {config.required_checks_source}).")
    require_clean(root)
    repo = verified_repository(config, root, verified_repo)
    prs = pr_list(config, root, repo, handoff.branch)
    matching = [pr for pr in prs if pr["number"] == record.get("pr_number")]
    if len(matching) != 1 or matching[0]["state"] != "OPEN":
        raise Abort("Recorded open PR identity does not match GitHub")
    if any(pr["state"] == "OPEN" and pr["number"] != record["pr_number"] for pr in prs):
        raise Abort("Multiple open PRs exist for this feature branch; resolve manually")
    assert_pr_matches_revision(config, handoff, matching[0], record.get("pushed_sha"))
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
    try:
        latest = pr_details(config, root, repo, pr["number"])
    except Abort as exc:
        raise RemoteOutcomeUnknown(
            f"PR merge command returned, but GitHub confirmation was unavailable: {exc}. "
            "Inspect the PR before manually reconciling."
        ) from exc
    if latest["state"] != "MERGED" or not latest.get("mergedAt"):
        raise RemoteOutcomeUnknown("Merge command returned but GitHub does not confirm MERGED; "
                                   "inspect the live PR before another merge attempt")
    assert_pr_matches_revision(config, handoff, latest, record.get("pushed_sha"), merged=True)
    record["phase"] = "merged"
    save_checkpoint()
    print("GitHub merge confirmed. Local main synchronization is a separate recoverable step.")
    return repo


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
    expected_sha = record.get("pushed_sha") or record.get("commit_sha")
    if not expected_sha:
        raise Abort("Cannot confirm a merged PR without the current patch's recorded commit")
    merged = [pr for pr in pr_list(config, root, repo, handoff.branch)
              if pr["state"] == "MERGED" and pr.get("mergedAt")
              and pr["headRefOid"] == expected_sha
              and pr["baseRefName"] == config.base]
    if len(merged) != 1:
        raise Abort("GitHub has not confirmed exactly one merged PR for the current patch revision")
    pr = merged[0]
    if record.get("pr_number") is not None and record["pr_number"] != pr["number"]:
        raise Abort("Merged PR differs from the recorded PR number")
    assert_pr_matches_revision(config, handoff, pr, expected_sha, merged=True)
    return pr


def sync_base(config, handoff, root, record, save_checkpoint, *, verified_repo=None):
    require_clean(root)
    repo = verified_repository(config, root, verified_repo)
    details = pr_details(config, root, repo, record["pr_number"])
    if details["state"] != "MERGED" or not details.get("mergedAt"):
        raise Abort("Recorded merge is not confirmed by GitHub")
    if details.get("number") != record.get("pr_number"):
        raise Abort("Recorded PR number changed before synchronization")
    assert_pr_matches_revision(config, handoff, details,
                               record.get("pushed_sha") or record.get("commit_sha"), merged=True)
    record["local_base_head"] = sync_local_base(config, root)
    record["phase"] = "synced"
    save_checkpoint()
    print(f"Local {config.base} is synchronized after GitHub PR merge.")
