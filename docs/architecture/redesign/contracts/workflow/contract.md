# Workflow domain contract (proposed)

**Target package:** `apatch_lib/workflows/`.
**Status:** original R1 target proposal; see the implemented R2.3 value boundary
in `apatch_lib/workflows/contract.md`. Engine/state APIs remain future scope.

## Purpose and ownership

Own action applicability, phases, LOOSE/STRICT/FORCE policies, session links,
sequencing and guarded macros/goals, verification/commit scope, atomic
checkpoint/journal transitions and explicit action outcomes. Coordinate Git,
handoff, review and publication via their public APIs; do not parse their
private storage or wire formats. Persist only proven effects.

## Proposed API and models

- `api.plan_action(request: WorkflowRequest, snapshot: WorkflowFacts) -> ActionPlan`
  (pure read-only plan, not permission to execute).
- `api.execute_action(request: WorkflowRequest, ports: WorkflowPorts) -> ActionResult`.
- `api.inspect_session(session_id: str) -> SessionView` (read-only).
- `api.read_checkpoint(...) -> CheckpointSnapshot` (read-only).
- `api.verify_resume(...) -> ResumeEvidence` (no replay).
- `api.WorkflowPhase`, `OperationOutcome`, `ActionResult`,
  `WorkflowRecord`, `StateDocument` (implemented R2.3); `FeatureSession` and
  `ExecutionPlan` remain proposals. `ActionResult` is defined in `results.py`.

Current source: `workflow.Workflow`, `loose.LooseActions`,
`force.ForceActions`, `branch_patch.BranchPatchActions`, `planner`, `sequence`,
`macros`, `state`, `operation_events`, `session`, `session_continuation`,
`commit_scope`, `context`, `action_executor`, `action_applicability`,
`core.actions`, `core.enums`, and workflow portions of `core.contracts`.

## Invariants and failure semantics

- LOOSE is default and permits user edits/alternate branches as specified;
  STRICT keeps phase guards; FORCE is verified recovery, never force push.
- Preserve existing `0..13` operations and original `opSeq`, `handoffSeq`,
  `goal`, `followup`, `featureBranch`, no-op and unknown-remote semantics.
- One coordinator owns state and journal updates under the correct lock.
  Never infer a successful action from changed Git state alone.
- CHK evidence binds the exact policy, Git HEAD, index and worktree bytes;
  required review must also bind the current checked snapshot before CMT.
- After interruption, reconcile observed effects before continuing.
  `skipApproves` skips prompts only, never verification.

**Dependencies:** `configuration` settings, `git.api`, `handoff.api`,
`publication.api`, `review.api`, `core` and `common`; no `audit`/`runtime`
imports and no private domain files.

**Tests:** `test_sequences.py`, `test_modes.py`, `test_planner.py`,
`test_feature_sessions.py`, `test_session_continuation.py`,
`test_guarded_commit.py`, `test_operation_journal.py`, `test_status.py`,
`test_macros.py` and `char_workflows`/`char_recovery`.
