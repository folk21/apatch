# APATCH-PLAN-001 — Orchestrator Implementation Plan

**Status:** ADVISORY DRAFT. This plan does not authorize implementation.

**Specification:** [APATCH-SPEC-001](../active/spec-apatch-orchestrator.md).

**P0 requirements:** [APATCH-SUB-001](../active/subspecs/subspec-01-workflow-control.md). **P1 history/audit requirements:** [APATCH-SUB-002](../active/subspecs/subspec-02-state-history-audit.md).

## Principles

Complete small independently tested increments. Preserve existing CLI, handoff JSON, history/state migrations, safe extraction, and GitHub gates. Do not combine behavioral code changes with unrelated refactoring. Each stage needs focused unit/mock tests, local temporary-Git integration tests where applicable, documentation updates, and `sh ./run_tests.sh` before completion.

## P0 — First priority

| Stage | Owner and work | Acceptance evidence |
| --- | --- | --- |
| **P0.1 — Current status and next operation feedback** | New `apatch_lib/status.py` plus CLI/menu, local Git evidence, branch provenance, and recommendation logic. | SUB-001 AC-01/02/15–18; read-only and offline tests in all modes. |
| **P0.2 — Project PR approval policy** | `apatch_lib/model.py`, `apatch_lib/github.py`, `.apatch/config.yaml` parser and usage docs: optional `require_review_approval` override, default unchanged. | AC-03/04, mock `reviewDecision` variants, CI and GitHub rejection unaffected. |
| **P0.3a — Registry validation and ordering** | New small `apatch_lib/created_patches.py` or another single owner; compare optional local registry to legacy-compatible `AppliedPatchHistory`. Guard `BAP`/`APL` in all modes *before* side effects. | AC-05/06/08, invalid lines/duplicates/symlinks, history migration tests. |
| **P0.3b — Registry metadata transport** | Extend archive inspection/application to recognize a reserved `.apatch/created_patches.txt` member, validate append-only prefix, and store atomically as non-Git metadata. | AC-07, repeated ZIP, failed extraction/retry, ignored-file handling, no worktree false positives. Activate new ChatGPT packaging directive only once this is stable. |
| **P0.4a — `opSeq` core** | `apatch.py`, `apatch.sh`, `apatch_lib/workflow.py`: parse a list of existing operation IDs, dispatch sequentially, refresh state between steps, stop on failure and report the complete step context. | AC-09/11/12/13/14, `skipApproves` true/false, shell/Python parser parity, timeout recovery. |
| **P0.4b — Multiple handoffs** | Add explicit optional `handoffSeq` mapping for `BAP`/`APL`, retaining prior cycle state; verify preflight against duplicate or missing inputs. | AC-10/11, successive patches on one branch, combined commit/deferred push, STRICT rejection. |

Stage P0.3b and P0.4b depend on developer acceptance of [open decisions](../active/subspecs/subspec-01-workflow-control.md#7-open-decisions). The user-facing P0 features remain in the **first sub-spec** even when delivered over multiple safe increments.

### P0.1 — File-level implementation: current status and suggestions

**Prerequisites:** confirm `Workflow` dispatch, `StateStore` access, handoff selection, existing Git helper signatures, and branch-origin fields in the verified source snapshot. Preserve `0..9` unchanged and add `10 [STS]`. `STS` must not require reloading the ZIP if a unique stored workflow can be resolved.

| File | Exact planned change |
| --- | --- |
| `apatch_lib/status.py` (**new**) | Define `PatchStatus`, `StatusFact`, `EvidenceLevel` and read-only status builder; centralize `recommend_next_action`, not UI formatting or Git mutations. |
| `apatch_lib/model.py` | Add typed status/evidence objects only if the existing model layout makes this their appropriate owner; retain handoff schema v1. |
| `apatch_lib/state.py` | Expose read-only workflow enumeration and lookup; record branch creation/reuse provenance on future branch operations without inventing it for legacy records. |
| `apatch_lib/branch_patch.py` | Return the actual branch origin (`CREATED`/`REUSED`) when known; do not conflate planned and actual branch names. |
| `apatch_lib/gitutil.py` | Reuse/extend safe, side-effect-free branch, HEAD, and commit existence inspection. |
| `apatch_lib/github.py` | Optionally expose bounded remote PR state inspection; no implicit API calls in default local-only `STS`. |
| `apatch_lib/workflow.py` | Append operation `10 [STS]`, menu label and dispatcher; show suggested number/code following all relevant successful actions and explicit failures/no-ops. |
| `apatch.py`, `apatch.sh` | Accept `op=STS` and `op=10` through existing direct-action parsing; do not break numeric or mnemonic forms. |
| `tests/test_apatch.py` | Add synthetic Git state cases, legacy record cases, menu/CLI parity, ambiguity, unknown/contradictory remote results, and state immutability assertions. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md` | Explain status output, fact confidence, no-network default, provenance, and recommendation caveats. |

**Core pseudocode:**

```python
def inspect_current_patch(context, selected_patch=None):
    candidates = state.list_workflows(context.repository)
    workflow = select_exact_or_unique_workflow(
        candidates, selected_patch, context.current_branch
    )
    if workflow is ambiguous:
        return StatusError("AMBIGUOUS_PATCH", workflow.candidate_names)

    record = state.read_workflow(workflow)  # Never mutate on inspection.
    local = gitutil.inspect_local_facts(context.repository)
    facts = compare_observed_with_recorded(record, local)
    if context.remote_verification_requested:
        facts += github.inspect_remote_facts_with_timeout(record)

    # Unknown evidence must not be silently treated as a successful checkpoint.
    facts = mark_unknown_and_conflicting_fields(facts)
    return PatchStatus(
        workflow=workflow,
        facts=facts,
        next_action=recommend_next_action(facts, context.mode),
    )

def on_action_completed(operation, result, context):
    display_actual_outcome(operation, result)
    if result.failed or result.cancelled:
        display_recovery_guidance(result)
        return
    status = inspect_current_patch(context)
    display_next_action_number_and_code(status.next_action)
```

**Edge cases:** no active workflow; same ZIP filename in multiple workflow keys; local branch changed manually; patch applied in a reused branch; several handoffs before one commit; missing historical branch-origin fields; detached HEAD; remote PR number stale; GitHub timeout; `SYN` already completed by merge behavior. `STS` and recommendations do not relax mode gates or require a new approval. For every `STS` test, compare state-file bytes, Git status, refs, and working-tree bytes before/after.

**Acceptance checkpoint:** SUB-001 AC-01/02/15–18, focused CLI tests, full project tests, and a complete read-only console fixture for an applied-but-uncommitted patch.

### P0.2 — File-level implementation: project review policy

| File | Exact planned change |
| --- | --- |
| `apatch_lib/model.py` and the confirmed project-config loader | Parse optional boolean `require_review_approval` from target `.apatch/config.yaml`; inherit global value when absent. Reject strings, integers, and null when a boolean is required. |
| `apatch_lib/github.py` | Enforce effective local review rule only after checking PR identity, head, base, mergeability, required checks, and remote status. Never bypass GitHub server protections. |
| `apatch_lib/workflow.py` | Display effective rule and its `project`/`global` origin before `MRG`; keep normal interactive approval independent. |
| `tests/test_apatch.py` | Mock absent approval/approved/pending, CI rejection, stale head, changed PR, and GitHub rejection with the override on/off. |
| `docs/USAGE.md` | Document default inheritance and project override examples. |

```python
effective_review_requirement = (
    project_config.require_review_approval
    if project_config.has_explicit_review_setting
    else global_config.require_review_approval
)
assert_verified_pr_identity_and_mergeability()
assert_required_ci_checks_pass()
if effective_review_requirement:
    assert_review_decision_is_approved()
perform_standard_merge_with_no_bypass_flags()
```

**Acceptance checkpoint:** SUB-001 AC-03/04; missing approvals may pass the local gate only under explicit project override, while CI, branch protections, stale PR heads, and GitHub failures still block.

### P0.3a/b — File-level implementation: patch registry and metadata transport

| File | Exact planned change |
| --- | --- |
| `apatch_lib/created_patches.py` (**new**, proposed owner) | Strict UTF-8 registry parser, ZIP basename validation, duplicate detection, prefix ordering, and append-only comparison. |
| `apatch_lib/patch_history.py` | Expose reliable applied filename lookup over current and legacy journal entries; preserve distinction between created and applied. |
| `apatch_lib/patch.py` | Invoke ordering preflight before extraction; later recognize reserved `repository/.apatch/created_patches.txt` metadata member and exclude it from source extraction/changed-file comparisons. |
| `apatch_lib/branch_patch.py` | Run ordering preflight before branch switching/creation in `BAP`. |
| `apatch_lib/state.py` | Reuse locked/atomic persistence utilities for registry updates; protect state on interrupted writes. |
| `apatch_lib/model.py` | Validate reserved path, member type, malformed registry contents, and final handoff digest without widening unsafe archive permissions. |
| `tests/test_apatch.py` | Add ordering, duplicates, malformed names, symlinks, prefix mismatch, ZIP member classification, retry, and migration cases. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md` | Document optional registry and bootstrap sidecar; activate ZIP metadata packaging instructions only after runtime support passes tests. |

```python
def preflight_patch_order(current_basename, created_registry, applied_history):
    if created_registry is absent:
        return LegacyCompatibleNoRegistry()
    names = parse_validate_unique_basenames(created_registry)
    if current_basename not in names:
        raise PatchOrderError("Current patch is not registered")
    prior_names = names[:names.index(current_basename)]
    for predecessor in prior_names:
        if predecessor not in applied_history:
            raise PatchOrderError(
                f"Patch {predecessor} has not been applied!"
            )

def receive_reserved_registry_member(existing, incoming):
    if not incoming.startswith_exact_lines(existing):
        raise RegistryPrefixConflict()
    stage_validated_update_for_atomic_commit(incoming)
    # Do not extract this metadata as a tracked source file.
```

**Ordering of implementation:** deliver P0.3a first using existing local registry only; independently test all modes. Deliver P0.3b only after approving the reserved archive member and verifying no changed-path contamination. The stage SHALL never permit FORCE or `skipApproves` to skip missing predecessors. Retain checksum validation and path-safety checks independent from ordering.

**Acceptance checkpoint:** SUB-001 AC-05/06/07/08 and negative archive-path tests, including failure between source extraction and registry persistence without partial ledger truncation.

### P0.4a/b — File-level implementation: sequential operations and multiple handoffs

| File | Exact planned change |
| --- | --- |
| `apatch_lib/sequence.py` (**new**) | Define `OperationSequence`, parsed operation tokens, progress/error DTOs, preflight, single-threaded execution, and deterministic stop/recovery reporting. Reuse existing operation handlers instead of duplicating Git logic. |
| `apatch_lib/workflow.py` | Provide a single operation-dispatch method callable from interactive, `op=`, or sequence contexts; produce accurate per-step results and refresh state between actions. |
| `apatch.py` | Add mutually exclusive `opSeq` argument; reject malformed/empty/unknown/duplicate-sensitive sequence forms before side effects; pass `skipApproves` and mode unchanged. |
| `apatch.sh` | Normalize shell `opSeq=...` and proposed `handoffSeq=...`; preserve spaces/argument boundaries and existing CLI aliases across macOS/Linux shells. |
| `apatch_lib/model.py` | Validate optional handoff sequence input, exact mapping of `BAP`/`APL` to selected handoffs, and patch identity changes. |
| `apatch_lib/loose.py`, `apatch_lib/force.py` | Check that shared branch and manual-operation semantics remain unchanged when an action is sequence-driven; avoid alternative special-case state machines. |
| `tests/test_apatch.py` | Parser parity, op-order, no-interaction, non-TTY, intermediate Git failure, network timeout, sequence stop, and two ZIPs/one deferred commit cases. |
| `docs/USAGE.md` | Show both acronym/number forms, handoff selection, progress, error summary, and explicit manual resume procedure. |

```python
def prepare_sequence(op_seq, handoff_seq, context):
    if context.single_op_was_provided:
        raise CliError("op and opSeq are mutually exclusive")
    actions = parse_tokens_resolving_number_and_mnemonic(op_seq)
    reject_empty_or_unknown_elements(actions)
    handoffs = resolve_explicit_handoff_mapping(actions, handoff_seq)
    reject_ambiguous_repeated_apply_of_same_patch(actions, handoffs)
    preflight_required_inputs_without_mutating_repository()
    return OperationSequence(new_id(), actions, handoffs)

def execute_sequence(sequence, context):
    for index, action in enumerate(sequence.actions, start=1):
        print_start(index, len(sequence.actions), action, context)
        refresh_git_and_workflow_context()
        try:
            result = workflow.execute_existing_operation(action, context)
        except Cancelled as error:
            return report_stop(index, action, "CANCELLED", error)
        except RemoteOutcomeUnknown as error:
            return report_stop(index, action, "INDETERMINATE", error)
        except Exception as error:
            return report_stop(index, action, "FAILED", error)
        if not result.success:
            return report_stop(index, action, result.outcome, result.error)
        print_end_with_next_scheduled_and_recommended_action(result)
    return print_sequence_success_summary()
```

At every failure, print step `i/N`, number/code, selected patch, branch, phase, last completed action, observed versus uncertain effects, remaining actions, exit status, and safe reconciliation instructions. No automatic rollback, hidden command retry, or continued execution after cancellation. `skipApproves=true` may suppress confirmations but MUST NOT skip safety gates. P0 does not yet require persisted per-action runs; P1.1 will add them without changing sequence behavior.

**Acceptance checkpoint:** SUB-001 AC-09–14, test failed step 1 versus failed step N, missing/invalid handoff, duplicate `BAP,APL` without distinct handoffs, CI rejection, and timed-out GitHub operations.

## P1 — Execution history, global audit, and scheduled quality checks

### P1.1 — File-level implementation: execution journal (APATCH-SUB-002)

**Dependency:** stable standalone and sequence dispatch; exact lock acquisition order confirmed in `state.py` and `workflow.py`. Do not change real Git side effects as part of the journaling stage. Existing `apply_patch.state.json` stays the single durable state file.

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

**Additional P1 format-adapter work (separate future sub-spec):** design and implement secure Git-native patch ingestion without changing the existing ZIP contract. Inspect the current archive/application modules, define a format-aware handoff validator, preflight via safe Git patch applicability checks, preserve manual worktree changes and deferred commits, and add cases for renames, deletions, binaries, malicious paths, conflicts, retries, and both `git diff` and `git format-patch` input forms. Do not implement until its dedicated sub-spec establishes accepted syntax and safety policy.

### P1.3 — Scheduled check adapters (future dedicated sub-spec required)

1. Define check contract and argv adapter; migrate configured canonical checks behind a compatibility facade without changing their behavior.
2. Add trigger policies for each action, after every N patches, accumulated file/byte thresholds, and elapsed intervals. Persist last-run evidence and skip reasons.
3. Add targeted/unit, lint/static, security, integration/E2E/UI/load check classes, with project-configured timeouts and blocking rules.

**Verification:** tests for scheduling thresholds, stale evidence, mandatory versus advisory failures, command failures/timeouts, and output redaction.

## P2 — Repository health and SDD stage tracking

1. Introduce a versioned evidence record keyed by repository/branch/HEAD, with `UNKNOWN`, `HEALTHY`, `DEGRADED`, and `BLOCKED` states.
2. Define optional spec/stage identity metadata and explicit completion criteria; trigger expanded checks at declared final milestones.

**Verification:** drift/revision invalidation, unknown-check semantics, stage completion guard, migration and concurrency tests.

## P3 — Independent review and plugin extensions

1. Add an external-review adapter with explicit endpoint/CLI choice, budget, cooldown, patch-size thresholds, and data redaction.
2. Add registration of independent check adapters and structured reports without growing the core `Workflow` class.

**Verification:** mocked HTTP/CLI adapters, timeout/rate-limit/retry behavior, budget enforcement, opt-out defaults, and no covert network calls.

## Progress and rollback policy

The current stage remains `GENSPEC / DRAFT` until the developer approves it. Each implementation stage SHALL leave a separately testable handoff. A failed or partial Git/GitHub action is reconciled against live state; no automated force-push, hard reset, or rollback of user work is permitted.
