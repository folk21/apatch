"""Explicit, non-staging formatter operation before canonical verification."""

import os

from .commit_scope import policy_fingerprint
from .core.enums import WorkflowPhase
from .gitutil import (current_branch, head, run, worktree_change_details,
                      worktree_inventory)
from .model import Abort


def _print_changes(before, after):
    details = worktree_change_details(before, after)
    if not details:
        print("==> FMT: no Git index or worktree changes detected", flush=True)
    else:
        print(f"==> FMT: {len(details)} changed path(s); all contents preserved", flush=True)
        for path, kinds in details[:24]:
            print(f"    {path!r}: {', '.join(kinds)}", flush=True)
        if len(details) > 24:
            print(f"    ... and {len(details) - 24} additional path(s)", flush=True)
    return details


def _assert_safe_delta(before, after):
    for path in before.keys() | after.keys():
        old, new = before.get(path), after.get(path)
        if (old is not None and new is not None
                and (old.symlink_target != new.symlink_target
                     or (old.kind != new.kind and 'symlink' in {old.kind, new.kind}))):
            raise Abort(f"FMT_SYMLINK_CHANGED: Symlink identity changed for {path!r}; "
                        "review preserved files before CHK")
        if (old is None and new is not None and new.kind == "symlink"):
            raise Abort(f"FMT_SYMLINK_CHANGED: New symlink at {path!r}; "
                        "review preserved files before CHK")


def _index_entries(root):
    """Inspect the whole Git index, including paths entering the changed set."""
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


def run_formatters(workflow):
    """Execute explicitly configured format commands without staging or verifying."""
    commands = workflow.config.format_commands
    if not commands:
        raise Abort("FMT requires format_commands in .apatch/config.yaml; "
                    "no formatter was executed")
    if workflow.phase not in {WorkflowPhase.PATCH_APPLIED.value,
                              WorkflowPhase.VERIFIED.value}:
        raise Abort("FMT requires an applied, uncommitted patch; use APL,BRN first")
    branch = current_branch(workflow.root)
    if (not branch or branch == workflow.config.base
            or branch != workflow.applied_branch):
        raise Abort("FMT requires the recorded applied feature branch after BRN")
    baseline_head = head(workflow.root)
    if workflow.record.get("before_patch_head") != baseline_head:
        raise Abort("FMT_HEAD_DRIFT: HEAD differs from the applied patch baseline")
    if workflow.record.get("remote_url"):
        workflow.assert_remote_unchanged()

    before = worktree_inventory(workflow.root)
    before_index = _index_entries(workflow.root)
    baseline_policy = policy_fingerprint(workflow.root, workflow.config)
    for key in ("verified_fingerprint", "verified_head", "verified_branch",
                "verified_commit", "guarded_verification"):
        workflow.record.pop(key, None)
    workflow.record["phase"] = WorkflowPhase.PATCH_APPLIED.value
    workflow.persist()

    print("==> FMT: canonical verification invalidated; CHK is required after formatting")
    for index, command in enumerate(commands, start=1):
        print(f"==> FORMAT {index}/{len(commands)}", flush=True)
        failure = None
        try:
            run(list(command), workflow.root, stream_output=True,
                timeout=workflow.config.check_timeout_seconds,
                idle_timeout=workflow.config.check_idle_timeout_seconds)
        except (Abort, KeyboardInterrupt) as exc:
            failure = exc
        after = worktree_inventory(workflow.root)
        _print_changes(before, after)
        if current_branch(workflow.root) != branch or head(workflow.root) != baseline_head:
            raise Abort("FMT_HEAD_DRIFT: Branch or HEAD changed during formatting; "
                        "edits were preserved")
        after_index = _index_entries(workflow.root)
        if before_index != after_index:
            changed_index = sorted(name for name in before_index.keys() | after_index.keys()
                                   if before_index.get(name) != after_index.get(name))
            raise Abort(f"FMT_INDEX_CHANGED: Git index changed for {changed_index[0]!r}; "
                        "review staged edits before CHK")
        _assert_safe_delta(before, after)
        if policy_fingerprint(workflow.root, workflow.config) != baseline_policy:
            raise Abort("FMT_CONFIG_DRIFT: Project check policy changed during formatting")
        if failure is not None:
            raise failure
    print("==> FMT: completed; review formatting changes and run CHK", flush=True)
    return True
