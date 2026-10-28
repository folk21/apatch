# APATCH-PLAN-001-P1 — Execution History and Audit Implementation Plan

**Status:** ARCHIVED / ADVISORY — SUB-002 P1.1–P1.2 completed and accepted by the developer on 2026-10-28.

**Normative owner:** [APATCH-SUB-002](subspec-02-state-history-audit.md). **Parent:** [APATCH-SPEC-001](../../active/spec-apatch-orchestrator.md).

This is the original P1.1/P1.2 implementation plan split out of the former shared PLAN-001. Later P1 proposals remain in the active umbrella plan, not in this completed sub-specification.

## P1 — Execution history and global audit

### P1.1 — File-level implementation: execution journal (APATCH-SUB-002)

**Dependency:** stable standalone and sequence dispatch; exact lock acquisition order confirmed in `state.py` and `workflow.py`. If P0.5 is already implemented, its tool-wide progress ledger remains a concise **cross-project projection**; the P1 journal is a richer **per-target evidence log**, not a second independent writer of the same progress event. Reuse/correlate stable event IDs where possible. Do not change real Git side effects as part of the journaling stage. Existing `apply_patch.state.json` stays the single durable state file.

| File | Exact planned change |
| --- | --- |
| `apatch_lib/operation_events.py` (**new**) | Define `OperationRun`, outcome enum, sequence linkage, bounded error snapshot, and event serialization/validation. |
| `apatch_lib/state.py` | Add schema-v2 migration and atomic `start_run`/`finish_run` transactions under existing locks; retain all workflow records and unknown forward-compatible fields. |
| `apatch_lib/migration.py` | Extend actual version migration if that is its verified responsibility; never overwrite generic current state from older legacy sources. |
| `apatch_lib/workflow.py` | Wrap numbered lifecycle operations with start/result journal updates exactly once per attempt. Exclude read-only `STS` and future `AUD`. |
| `apatch_lib/sequence.py` | Supply sequence ID and one-based index to the shared operation wrapper; avoid writing a second duplicate event. |
| `apatch_lib/gitutil.py`, `apatch_lib/github.py` | Expose evidence/uncertain remote side-effect classifications where current results cannot reliably distinguish failure from ambiguity. |
| `apatch_lib/model.py` | Define persisted event schema/validation and safe error/identity bounds. |
| `tests/test_apatch.py` | v1-to-v2 migration, malformed v2 rejection, parallel writers, interrupted process, retries, no-op, cancellation, timeout, multiple handoffs, and secret redaction. |
| `docs/ARCHITECTURE.md`, `docs/USAGE.md` | Describe journal facts versus workflow checkpoints, schema evolution, and inspection semantics. |

```python
def run_numbered_workflow_operation(action, context):
    if action.code in ("STS", "AUD"):
        return execute_read_only_inspection(action, context)

    run_id = state.atomic_append_run(
        operation=action.identity, context=context, outcome="STARTED"
    )
    try:
        result = workflow.execute_without_journal_recursion(action, context)
        state.atomic_finish_run(
            run_id, classify_outcome(result), verified_facts(result)
        )
        return result
    except RemoteOutcomeUnknown as error:
        state.atomic_finish_run(run_id, "INDETERMINATE", safe_error(error))
        raise
    except UserCancelled as error:
        state.atomic_finish_run(run_id, "CANCELLED", safe_error(error))
        raise
    except Exception as error:
        state.atomic_finish_run(run_id, "FAILED", safe_error(error))
        raise

def recover_unfinished_runs(records, observed_repository):
    for record in records.where(outcome="STARTED"):
        if owner_process_is_confirmed_alive(record):
            continue
        mark_unresolved_without_inventing_git_effects(record)
        offer_external_reconciliation_if_needed(record)
```

Use distinct atomic lock windows for `STARTED` and terminal writes; release them before calling the underlying operation to avoid a nested state lock or deadlock. If persisting a completion result itself fails, preserve an explicit error and rely on subsequent factual reconciliation; do not claim the journal is complete. A retry creates a *new* run and checks externally observable idempotence before repeating remote side effects. Do not infer a patch/commit one-to-one relationship when several ZIPs were batched into one commit.

**Acceptance checkpoint:** SUB-002 AC-H01–H07; synthetic concurrent writers show no lost events; old state reads and round-trips unchanged existing fields; never persist test output or credentials.

### P1.2 — File-level implementation: global patch audit (APATCH-SUB-002)

**Dependency:** status evidence semantics in P0.1 and operation history from P1.1. Register `11 [AUD]` without renumbering other operations. The default audit is offline and read-only.

| File | Exact planned change |
| --- | --- |
| `apatch_lib/reconciliation.py` (**new**) | Build cross-source patch identity index, confidence/severity findings, stable ordering, and remediation suggestions; share fact comparison logic with `status.py`. |
| `apatch_lib/created_patches.py`, `apatch_lib/patch_history.py` | Provide strictly parsed generation/application ordering and legacy-compatible history lookups. |
| `apatch_lib/state.py`, `apatch_lib/operation_events.py` | Provide immutable snapshots of workflows and runs; never mutate state on audit. |
| `apatch_lib/status.py`, `apatch_lib/gitutil.py` | Reuse verified/local/recorded/conflicting fact classification and Git evidence across all patch identities. |
| `apatch_lib/github.py` | Optional bounded remote branch/PR reconciliation with explicit unknown results on network failure. |
| `apatch_lib/workflow.py`, `apatch.py`, `apatch.sh` | Register `11 [AUD]`, direct acronym/number/interactive parity, and optional remote-query switch after the sub-spec resolves spelling. |
| `tests/test_apatch.py` | Missing/duplicate/out-of-order patches, shared branches, manual operations, unknown remote, v1 history, and strict immutability tests. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md` | Document audit coverage limitations, health/findings output, and read-only safety. |

```python
def audit_all_known_patches(repository, verify_remote=False):
    generated = registry.read_optional_created_list(repository)
    applied = patch_history.read_legacy_compatible(repository)
    workflows = state.read_all_workflows(repository)
    runs = state.read_operation_runs(repository)
    local = gitutil.inspect_local_git_repository(repository)
    remote = github.inspect_with_timeout(repository) if verify_remote else None

    patch_ids = union_of_known_patch_ids(generated, applied, workflows, runs)
    findings = []
    for patch_id in patch_ids:
        facts = reconcile_one_patch(patch_id, generated, applied,
                                    workflows, runs, local, remote)
        findings += detect_missing_skipped_stale_or_conflicting_steps(facts)
    findings += detect_global_duplicates_and_ordering_problems(generated, applied)
    return AuditReport(
        findings=sorted_by_severity_then_patch(findings),
        coverage=describe_unknown_or_unavailable_sources(remote, generated),
        recommendations=derive_non_mutating_recovery_steps(findings),
    )
```

**Acceptance checkpoint:** SUB-002 AC-A01–A05; compare state JSON bytes, applied/generated registries, HEAD, Git refs, staged and unstaged paths before/after `AUD`. When GitHub is unreachable, an offline report must still complete with explicit `UNKNOWN` remote facts.
