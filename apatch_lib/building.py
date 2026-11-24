"""Run an explicit build without granting canonical verification evidence."""

from .commit_scope import policy_fingerprint
from .mo_core.enums import WorkflowPhase
from .mo_git.api import index_entries
from .gitutil import current_branch, head, run, worktree_change_details, worktree_inventory
from .model import Abort


def run_build(workflow):
    """Run configured build commands with drift checks and preserved output."""
    commands = workflow.config.build_commands
    if not commands:
        raise Abort("BLD requires build_commands in .apatch/config.yaml; no build ran")
    if workflow.phase not in {WorkflowPhase.PATCH_APPLIED.value,
                              WorkflowPhase.VERIFIED.value}:
        raise Abort("BLD requires an applied, uncommitted patch; use APL,BRN first")
    branch = current_branch(workflow.root)
    if (not branch or branch == workflow.config.base
            or branch != workflow.applied_branch):
        raise Abort("BLD requires the recorded applied feature branch after BRN")
    original_head = head(workflow.root)
    if workflow.record.get("before_patch_head") != original_head:
        raise Abort("BLD_HEAD_DRIFT: HEAD differs from the applied patch baseline")
    workflow.assert_remote_unchanged()

    baseline = worktree_inventory(workflow.root)
    baseline_index = index_entries(workflow.root)
    baseline_policy = policy_fingerprint(workflow.root, workflow.config)
    for field in ("verified_fingerprint", "verified_head", "verified_branch",
                  "verified_commit", "verified_policy_fingerprint", "guarded_verification", "code_review"):
        workflow.record.pop(field, None)
    workflow.record["phase"] = WorkflowPhase.PATCH_APPLIED.value
    workflow.persist()

    print("==> BLD: previous CHK/REV evidence invalidated; build only", flush=True)
    for index, command in enumerate(commands, start=1):
        print(f"==> BUILD {index}/{len(commands)}", flush=True)
        failure = None
        try:
            run(list(command), workflow.root, stream_output=True,
                timeout=workflow.config.check_timeout_seconds,
                idle_timeout=workflow.config.check_idle_timeout_seconds)
        except (Abort, KeyboardInterrupt) as exc:
            failure = exc
        after = worktree_inventory(workflow.root)
        if current_branch(workflow.root) != branch or head(workflow.root) != original_head:
            raise Abort("BLD_HEAD_DRIFT: Branch or HEAD changed during build; edits preserved")
        if baseline_index != index_entries(workflow.root):
            raise Abort("BLD_INDEX_CHANGED: Build modified the Git index; inspect preserved edits")
        if baseline != after:
            changes = worktree_change_details(baseline, after)
            for name, kinds in changes[:20]:
                print(f"    {name!r}: {', '.join(kinds)}", flush=True)
            raise Abort("BLD_WORKTREE_CHANGED: Build altered visible repository files; "
                        "review preserved edits before CHK")
        workflow.assert_remote_unchanged()
        if policy_fingerprint(workflow.root, workflow.config) != baseline_policy:
            raise Abort("BLD_CONFIG_DRIFT: Project check policy changed during build")
        if failure is not None:
            raise failure
    print("==> BLD: SUCCESS; canonical CHK was not executed", flush=True)
    return True
