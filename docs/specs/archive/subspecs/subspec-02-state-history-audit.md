# APATCH-SUB-002 — Operation Execution History and Global Patch Reconciliation

**Status:** ACCEPTED / ARCHIVED — developer confirmed completed P1.1–P1.2 work on 2026-10-28. Historical proposals are retained as originally written.

**Parent:** [APATCH-SPEC-001](../../active/spec-apatch-orchestrator.md). **Advisory stages:** [archived implementation plan](subspec-02-state-history-audit-implementation-plan.md).

## 1. Purpose and dependencies

This sub-spec defines (1) durable **per-target** evidence records of every attempted workflow operation and its observed result, and (2) a read-only audit of previous patches **within that target repository**. It builds on [SUB-001](subspec-01-workflow-control.md): current-patch `STS`, `created_patches.txt`, applied-patch history, `opSeq`, and the P0.5 tool-wide cross-project progress summary. P0.5 is a lightweight activity index; this sub-spec owns a richer journal and evidence reconciliation, which should correlate with cross-project event IDs without conflicting independent histories. Its journal implementation is P1.1; repository audit is P1.2 and may be delivered later without delaying SUB-001.

The current state file is `<target>/.apatch/apply_patch.state.json` (not `applied_patch_state.json`). Preserve its current workflow keys, phase checkpoints, and existing v1 readers during migration. Existing `.apatch/applied_patches.txt` retains authority over *recorded successful archive applications*; the created-patch registry tracks *generation order*. Neither file proves publication or PR merge.

## 2. Durable operation runs (P1.1)

### 2.1 Storage contract

Introduce a versioned `operation_runs` collection within the **existing** `apply_patch.state.json`. Each invocation of a workflow action with a number and mnemonic SHALL create a unique run record, even if it fails, performs no work, or is cancelled. The record SHALL contain:

- `run_id`, `operation.number`, `operation.code`, mode, target repository identity, and available patch/workflow identity;
- UTC start and finish time (a missing finish indicates interrupted or still-running work);
- `outcome`, optional `sequence.id` and one-based `sequence.index`;
- relevant before/after branch, HEAD, and phase references, when safely known;
- bounded/redacted failure category and explanatory message;
- separate **verified facts** establishing application, branch creation/reuse, checks, commit, push, PR creation, merge, or synchronization only when corresponding evidence exists.

At minimum, outcomes SHALL be `STARTED`, `SUCCEEDED`, `NO_OP`, `FAILED`, `CANCELLED`, `INTERRUPTED`, and `INDETERMINATE`. `SUCCEEDED` records operation success; it MUST NOT imply that every possible downstream action was performed. A timeout after a remote side effect may be `INDETERMINATE`, never automatically `FAILED` or `SUCCEEDED`. Unknown facts remain absent/unknown. A retry SHALL append a new run, not overwrite the historical attempt. Each run ID MUST be globally unique within the target state file.

The execution wrapper SHALL persist `STARTED` **before** calling the underlying workflow action and SHALL persist the terminal outcome after its result or error is known. A crash may leave `STARTED`; on next load, stale runs SHALL be shown as unresolved or marked `INTERRUPTED` only after safe process/reconciliation checks. Do not infer successful Git or GitHub effects merely from elapsed time or phase labels.

Persistence SHALL reuse target-project locking and atomic replacement, with no nested lock deadlocks. A schema migration (proposed v1 → v2) SHALL preserve existing state/history data, tolerate missing new fields, and define behavior for unsupported newer versions. Writes SHALL be bounded and shall never persist credentials, raw test output, complete private command streams, or uncontrolled exception traces. Archival/retention policy for long-running histories is a separate decision and MUST NOT silently delete records.

### 2.2 Read-only exceptions

Pure inspection operations `10 [STS]` and `11 [AUD]` SHALL NOT modify the state they inspect, including to record their own invocation. This is the only deliberate exception to recording every numbered workflow action. Their observed results appear in stdout and may optionally be exported as a separately requested report in a future stage.

### 2.3 Illustrative schema (not an instruction to overwrite existing keys)

```json
{
  "schema_version": 2,
  "workflows": {},
  "operation_runs": [
    {
      "run_id": "example-run-001",
      "operation": { "number": 7, "code": "PR" },
      "workflow_key": "example-workflow-key",
      "patch": "patch-B.zip",
      "mode": "LOOSE",
      "started_at": "2026-10-23T12:10:00Z",
      "finished_at": "2026-10-23T12:10:30Z",
      "outcome": "INDETERMINATE",
      "sequence": { "id": "example-sequence-001", "index": 6 },
      "before": { "phase": "pushed" },
      "after": { "phase": "pushed" },
      "error": { "category": "NETWORK_TIMEOUT", "message": "GitHub API timed out" }
    }
  ]
}
```

## 3. Global patch reconciliation (P1.2)

Register `11 [AUD]` for a full known-patch history audit, callable interactively, `op=11`, or `op=AUD`. Preserve all older action numbers. By default the audit SHALL inspect **local** evidence without GitHub network calls or modifications. Remote checks require an explicit opt-in option and bounded subprocess/network timeouts; connectivity failure SHALL degrade remote evidence to `UNKNOWN`, not hide local findings.

The audit SHALL reconcile:

1. Ordered entries in `.apatch/created_patches.txt`, if present.
2. Existing `.apatch/applied_patches.txt` and legacy journal formats.
3. All workflows and their checkpoints from `apply_patch.state.json`.
4. Operation runs and unresolved/indeterminate attempts.
5. Local branches, commit ancestry, Git HEAD and worktree facts.
6. Optional remote branches, pushed SHAs, PR lifecycle and merge facts.

For each patch, report what is **VERIFIED**, merely **RECORDED**, **UNKNOWN**, or in **CONFLICT**; describe unfinished workflow steps and relevant dependencies on earlier patches. At minimum, detect missing applications, unregistered applied patches, duplicate/ambiguous basenames, out-of-order applications, missing referenced branches/commits, skipped workflow steps, stale state, unresolved remote outcomes, and incompatible evidence. The absence of an optional created registry SHALL be an explicit coverage limitation, not a blanket failure. Historical state lacking branch-origin or run records SHALL remain readable and honestly incomplete.

The report SHALL include counts and patch-specific findings, severity (`ERROR`, `WARNING`, `INFO`), evidence source, and actionable *recommendations*, not automatic remediation. Do not change Git, workflow phase, history, or registry during an audit. Human remediation remains separate from `AUD`.

## 4. Cross-cutting failure and recovery rules

- A commit/push/PR result stored in an operation run is historical evidence, not permanent truth about current remote state.
- For ambiguous remote timeouts, reconcile the external effect before offering non-idempotent retries.
- Preserve individual runs for multiple patch ZIPs applied on the same branch and committed together; do not fabricate one-to-one patch/commit relationships.
- A partial or corrupt state write MUST NOT silently erase earlier run records; fail with an actionable recovery message.
- `skipApproves=true` changes confirmation behavior only; it cannot turn failed or unknown outcomes into success.
- `STS` and `AUD` share the same factual-confidence semantics and reconciliation primitives, while preserving different scopes.

## 5. Acceptance scenarios

| ID | Scenario | Required evidence/behavior |
| --- | --- | --- |
| AC-H01 | `APL` succeeds | Persist operation number `3`, code `APL`, timestamps, outcome, patch and verified effects |
| AC-H02 | User declines `MRG` | Persist `8 [MRG]` with `CANCELLED`; no merge claim |
| AC-H03 | `PR` API times out | Persist `INDETERMINATE`, do not presume PR creation or auto-retry |
| AC-H04 | Process is interrupted after `STARTED` | Preserve unresolved run; recover without fabricating effects |
| AC-H05 | `opSeq` stops at third operation | Distinct runs for each attempted step, common sequence ID and correct indexes |
| AC-H06 | Load existing schema-v1 state | Preserve all workflows and migrate safely without invented historical runs |
| AC-H07 | Concurrent attempts update state | No corrupted JSON, duplicate run IDs, lost events, or nested-lock deadlock |
| AC-A01 | Registry lists A, B, C; applied journal lists A, C | Identify missing B and out-of-order C with explicit evidence |
| AC-A02 | Previous push/PR marked successful but remote unavailable | Display recorded/unknown remote status, not verified success |
| AC-A03 | Stored commit SHA missing locally | Report `CONFLICT` or missing evidence; do not rewrite state |
| AC-A04 | `AUD` and `STS` invoked | No state, registry, worktree, or Git changes |
| AC-A05 | Historical registry absent | Continue audit and explain incomplete ordering coverage |

## 6. Open design decisions

1. Confirm exact CLI spelling for optional remote status/audit verification (do not overload `skipApproves`).
2. Confirm journal retention/export policy and maximum safe diagnostic size before implementation.
3. Confirm whether an explicit patch selector is needed for auditing just one archived workflow; `AUD` without a selector always means global scope.

Do not mark this document `ACCEPTED` or implement its requirements until the developer resolves the necessary choices.
