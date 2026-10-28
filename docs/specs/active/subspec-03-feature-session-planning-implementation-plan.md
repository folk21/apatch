# APATCH-PLAN-003 — Feature Session and Context-Aware Workflow Implementation

**Status:** ADVISORY / DRAFT (GENSPEC). **Normative contract:** [APATCH-SUB-003](subspecs/subspec-03-feature-session-planning.md). **Parent:** [APATCH-SPEC-001](spec-apatch-orchestrator.md).

No stage below authorizes product implementation without a subsequent DEFAULT request. The clean `efb94f794b06489c3d4898ffd42218f7b16e69fd` snapshot contains P1.2 `AUD`, typed `CheckWorktreeChanged` recovery, FS-00 linkage and FS-00R ZIP resume implementation and tests. This source evidence does not prove developer installation, formal acceptance or verification on every platform. Reinspect the actual repository HEAD before further work.

## 1. Source contracts and dependency order

Existing verified entry points include `apatch.py:main`, `normalize_arguments`, `resolve_selected_handoff`, and `resolve_sequence_zip_names`; `apatch_lib/workflow.py:Workflow`, `inspect_previous_cycles`, and `link_successful_previous_cycles`; `apatch_lib/presentation/execution.py:OperationPresentation.interactive`; `apatch_lib/sequence.py:OperationSequence`, `execute_sequence` and `validate_multi_handoff_actions`; `apatch_lib/loose.py:LooseActions.assert_followup_selection`, `apply_patch`, `verify`, `commit`, `push`; `apatch_lib/branch_patch.py:BranchPatchActions.prepare_branch_after_apply`; `apatch_lib/status.py:inspect_patch`, `select_record`, `recommend_next_action`; `apatch_lib/zip_resume.py` (FS-00R); and `apatch_lib/reconciliation.py:audit_repository`. FS-01 session persistence and the broader FS-02–FS-06 planner are not yet implemented.

Persisted evidence is owned by `apatch_lib/state.py`, `operation_events.py`, `patch_history.py`, `created_patches.py`, `params_cache.py`, and `progress.py`. Subprocess and GitHub boundaries belong to `gitutil.py` and `github.py`. The shared test harness lives in `tests/_support.py`. These are **verified source paths**; proposed `session.py`, `context.py` and `planner.py` do not yet exist.

Plan sequence: **FS-00 → FS-00R → FS-01 → FS-02 → FS-03 → FS-04 → FS-05 → FS-06**. FS-00R is now represented in the source; the next proposed feature-session stage is **FS-01**. FS-04 and FS-05 MUST pass before automated remote publishing is enabled in FS-06. Stage labels are scoped to APATCH-PLAN-003 and do not rename existing P0/P1 roadmap stages.

Every stage MUST pass focused synthetic Git integration tests and `sh ./run_tests.sh`; run `sh ./run_rare_checks.sh` at each patch handoff. Record concrete command results, Git state before/after, and platform limits. Never claim macOS behavior from Linux checks. Use disposable repositories and mocked `gh`; never test commit/push/merge against user repositories.

## FS-00 — Baseline reconciliation and correct checkpoint semantics

**Candidate status:** Implemented as a targeted corrective overlay pending integration and independent review. The inspection/consent phase is read-only; additive same-branch linkage is saved only after successful application and latest-journal confirmation. Rejected or cancelled `APL` does not change older relationships. This stage does not enable automatic explicit-ZIP resume or workflow macros.

**Objective:** Align verified baseline, fix the premature `superseded` bookkeeping defect, and establish a stable compatibility fixture before introducing new semantics. **Dependencies:** reconcile the P1.2 and CHK-recovery overlays. **Non-goals:** new CLI flags, altered GitHub behavior, session persistence, or changing existing follow-up eligibility.

| Path | Work |
| --- | --- |
| `apatch_lib/presentation/execution.py` | Keep `assert_followup_selection` and patch-order/duplicate guards before `inspect_previous_cycles` → action → confirmed `link_successful_previous_cycles`. No earlier-workflow relationship writes before an applied result. |
| `apatch_lib/workflow.py` | Keep `inspect_previous_cycles` read-only and `link_successful_previous_cycles` success-only; link only matching feature-branch workflows and preserve historical keys for legacy readers. |
| `apatch_lib/loose.py` | Ensure declines, ZIP validation errors, failed backups/extraction and interrupted applications cannot mark old workflows as replaced. Keep all current overlap backups and `followup=true` safety guards. |
| `tests/test_handoffs.py` | Add rejection after preflight (including overlap decline), failed extraction, and successful new follow-up cases. Assert state bytes/relationship fields and old worktree contents. |
| `tests/test_operation_journal.py` | Confirm failed/cancelled attempts are journaled once without a success claim or unrelated checkpoint mutation. |
| `docs/ARCHITECTURE.md`, `docs/USAGE.md` | Document observed checkpoint semantics only after the code behavior changes. |

Illustrative control flow:

```python
candidate = inspect_previous_workflows_without_writing()
validate_candidate_and_selected_archive()
result = apply_archive_with_existing_backups_and_history()
if result.is_confirmed_applied:
    atomically_link_successful_patch_to_previous_context(candidate, result)
else:
    preserve_previous_checkpoint_relationships()
```

**Recovery:** An old `superseded_by` does not justify deleting/resetting a patch; preserve it and report its weak evidentiary meaning. Do not silently migrate old records into a new session. **Acceptance:** SUB-003 FS-06, FS-09, FS-15, FS-17; repository bytes unchanged on cancellation except explicitly retained diagnostic state/run evidence.

## FS-00R — Explicit ZIP identity selection and deterministic resume

**Source status:** Implemented in the inspected `efb94f7` snapshot (`zip_resume.py` and regression coverage); independent stage acceptance is not recorded.

**Objective:** Accept an already-applied, explicitly named self-contained ZIP for `op=CHK` or a sequence beginning at a later operation without replaying `APL` or `BRN`, **and** make a repeated `APL,BRN` prefix idempotent when both steps are independently verified as already satisfied. Cover both initial ZIP-first and follow-up ZIPs applied directly on the existing feature branch. **Dependencies:** FS-00 reconciled baseline and preserved application journal. **Non-goals:** arbitrary operation skipping, creation of new feature sessions, a `goal=` option, unattended deliberate ZIP re-extraction, or broadening `followup=true` for new archives.

| Verified path / symbol | Required changes |
| --- | --- |
| `apatch.py:resolve_selected_handoff`, `main` | Classify positional ZIP as new or already-applied by exact workflow identity, not merely by its presence. If the requested first action is non-`APL`, select a uniquely verified completed application; if it is `APL`, recognize the last-applied matching ZIP and activate the verified idempotent path. Preserve the existing special `BRN` recovery after ZIP-first `APL`, status-only inspection and distinct-new-ZIP `handoffSeq` handling. |
| `apatch_lib/workflow.py:Workflow`, `interactive` | Centralize stable handoff-signature comparison, read-only verification that the selected ZIP is last applied in the active session, and step-specific evidence for already-satisfied `APL`/`BRN`. Reject stale/partial application records. An idempotent evaluation SHALL never invoke extraction or branch creation, nor infer a successful `CHK` from an applied checkpoint. |
| `apatch_lib/patch.py:handoff_from_zip`, `inspect` | Revalidate safe archive members, the repository and embedded metadata, and final SHA-256 if the ZIP remains available. Distinguish unavailable archive evidence from a conflicting archive; no extraction during selection. |
| `apatch_lib/state.py:read_state_snapshot`, `locked_state` | Verify selection using the current locked checkpoint immediately before any cache update; do not use an unlocked snapshot as authorization after possible concurrent changes. |
| `apatch_lib/patch_history.py:AppliedPatchHistory`, `apatch_lib/operation_events.py` | Correlate exact basename, ordered **last successfully applied ZIP**, planned branch, successful application and prior attempts; identify gaps, duplicate names and unverifiable migration records. A `zip_first=False` follow-up requires its **own** verified successful application evidence, not acceptance by branch name alone. Marking a step satisfied SHALL NOT fabricate a new APL/BRN success or append duplicate applied history. |
| `apatch_lib/params_cache.py:save_cached_handoff` | Atomically switch the active selection after verification, preserving the distinction between *selected* and *applied*. Reject malformed/symlinked cache targets and do not create a new history entry on reselection. |
| `apatch_lib/sequence.py:execute_sequence` | Keep the exact requested order and evaluate every step. Continue on `SUCCESS` or **proven** `ALREADY_SATISFIED`; stop on unverified `NO_OP`, `BLOCKED`, `ERROR` and unknown remote result. Accumulate executed, satisfied and not-executed steps without inventing a successful operation attempt. |
| `apatch_lib/status.py:select_record`, `apatch_lib/console.py`, `apatch_lib/presentation/execution.py` | Print selected ZIP, checkpoint phase, current/planned branch, evidence, no-replay assurance and a precise recovery command; show source/config command failures separately. Provide compact per-step `ALREADY_SATISFIED` notices and one final summary grouping executed, already-satisfied and unexecuted steps. Use subdued amber for satisfied skips, red only for actual blockers; respect non-TTY/`NO_COLOR`. |
| `tests/test_handoffs.py`, `tests/test_sequences.py`, `tests/test_config_cli.py`, `tests/test_operation_journal.py` | Add synthetic Git cases enumerated below; assert zero extra extraction/backup/history/branch operations on a successful resume or satisfied prefix and byte-identical protected state on rejected selection. |
| `docs/USAGE.md`, `docs/SECURITY.md` | Move copyable explicit ZIP-resume examples into current-facing documentation **only after** passing tests; clarify that repeated `APL` remains separately guarded. |

Algorithm sketch (names below are illustrative, not claims that helpers already exist):

```python
selection = parse_explicit_zip_or_cached_handoff()
stored = read_matching_workflow_and_history_without_writing(selection)
if requested_first_action == "APL" and not previously_applied(stored):
    execute_existing_new_application_guards(selection)
else:
    if not uniquely_proven_applied(stored, zip_digest, handoff_signature):
        return block_with_exact_evidence_and_recovery()
    with_locked_state_recheck_identity_and_git_context()
    select_active_handoff_atomically_without_applying_zip()
    for step in requested_sequence:
        evidence = reverify_step_specific_satisfaction(step)
        if evidence.proves_satisfied and step in ("APL", "BRN"):
            record_distinct_satisfied_outcome_without_repeating_mutation(step, evidence)
            continue
        execute_one_requested_step_with_existing_guards(step)
    summarize_executed_satisfied_and_unexecuted_steps()
```

**Focused matrix:** (1) ZIP-first `APL,BRN,CHK` fails because configured `./run-checks.sh` is missing; developer fixes script/config and invokes `same-ZIP opSeq=CHK,CMT,STS`; (2) manually edited source survives resume and fresh verification; (3) cache missing or naming another patch but explicit ZIP uniquely matches state/history; (4) already-applied follow-up archive reselected without `BRN`/`APL` regardless of `zip_first=False`; (5) new ZIP used with `CHK` is rejected as not applied; (6) same ZIP basename with changed bytes/metadata or wrong repository is rejected; (7) missing/corrupt state or applied history, interrupted `applying`, duplicate/mismatched branch or stale `superseded_by` produce inspection guidance; (8) exact last-applied ZIP on its intended current branch with `opSeq=APL,BRN,CHK,STS` skips only verified APL/BRN and executes CHK; (9) `opSeq=APL,BRN` with both steps satisfied completes successfully without source/index/ref/history changes and prints a consolidated summary; (10) older-than-last ZIP, same-name different digest, HEAD/remote drift or wrong current branch block idempotent skipping, even with `skipApproves=true`; (11) direct interactive intentional `APL` retains existing confirmation and overlap safeguards; (12) numeric/mnemonic `opSeq`, strict/force and legacy JSON remain compatible; (13) reselecting after a manual branch switch never permits unsafe unattended publication; (14) selected cache write failures do not damage existing cache; (15) no GH network operations are attempted in selection preflight; (16) `NO_COLOR`/non-TTY output clearly distinguishes satisfied versus failed actions; (17) an unproven `NO_OP` stops while a proven `ALREADY_SATISFIED` continues.

**Failure/recovery:** On identity failure, do not update cache, worktree/index, refs or applied history; report the exact mismatch and suggest `STS`/`AUD`. On a verified CHK failure, retain application evidence, stop the sequence before CMT, show the failing configured executable and project root, and offer an explicit same-ZIP `CHK,STS` restart. A later successful `CHK` cannot authorize a commit if HEAD, branch, check policy or checked bytes have drifted. A proven satisfied prefix leaves no user-owned source changes and does not repeat APL/BRN. Avoid treating the shell's malformed line-continuation whitespace as an `apatch` parser error; copyable examples SHALL use valid shell syntax. **Acceptance:** SUB-003 FS-06, FS-08, FS-15 and FS-21–34.

## FS-01 — Additive Feature Session persistence and migration

**Objective:** Represent multiple patches/commits/PR revisions as one feature development session without breaking existing per-ZIP journal and cache. **Dependencies:** FS-00R. **Non-goals:** adaptive execution, auto-commit, changing `opSeq`.

| Path | Work |
| --- | --- |
| `apatch_lib/session.py` (**new**) | Define typed `FeatureSession`, opaque stable ID, canonical repository/remote/base/feature identity, ordered patch associations, observed head revisions, commit/PR links and explicit terminal state. Validate all persisted IDs and bounded field sizes. |
| `apatch_lib/state.py` | Add session collection by backward-compatible schema migration; preserve all v1/v2 workflow, run and unknown compatible fields. Reuse locked atomic replacement; reject unsupported newer versions without rewriting. |
| `apatch_lib/workflow.py` | Provide opt-in linking of successful patch workflows to a selected session, without treating the latest cached ZIP as the session. |
| `apatch_lib/patch_history.py`, `apatch_lib/created_patches.py` | Keep existing immutable per-ZIP ordering and applied evidence; new session links reference these records rather than editing the journal. |
| `apatch_lib/params_cache.py` | Retain the active verified handoff selection and distinguish reselection from a new application. Never store the entire session in the cache. |
| `tests/test_operation_journal.py`, `tests/test_history.py`, `tests/test_handoffs.py` | v1/v2 migration, multi-ZIP one-commit links, reuse of branch name after previous verified merge, corrupted record, interrupted write, concurrent writers and opaque-ID stability. |

Proposed data outline (exact representation to be frozen at FS-01 design review):

```json
{
  "feature_sessions": {
    "<opaque-session-id>": {
      "repository": "<canonical-root>",
      "remote_url": "<verified-remote>",
      "base_branch": "main",
      "feature_branch": "feature/example",
      "patch_workflow_keys": ["<existing-workflow-key>"],
      "commit_shas": [],
      "pr_revisions": [],
      "status": "active"
    }
  }
}
```

Do not equate a new remote branch with a new session without checking ancestry and historical PR evidence. Unknown migration facts remain `UNKNOWN`. **Recovery:** retain original state backup/readability through old reader compatibility; do not drop the legacy `superseded_by` field. **Acceptance:** SUB-003 FS-03, FS-04, FS-15–17.

## FS-02 — Read-only evidence reconciliation and scenario classification

**Objective:** Return a deterministic `ContextReport` from actual local/remote state without doing any mutable operation. **Dependencies:** FS-01. **Non-goals:** invoking `APL`, creating commits, or modifying `STS`/P1.2 `AUD` evidentiary guarantees.

| Path | Work |
| --- | --- |
| `apatch_lib/context.py` (**new**) | Define evidence-bearing `ContextReport`, `GuardFinding` and `Scenario` types; classify new-base, active-uncommitted, previously-committed, previously-pushed/open-PR, explicitly selected already-applied ZIP-first or follow-up, missing configured check command, manual-drift, and unknown-remote states. |
| `apatch_lib/status.py` | Reuse read-only Git/phase facts without weakening current `inspect_patch` and `select_record` ambiguity handling. |
| `apatch_lib/reconciliation.py` | Reuse available local audit facts, but do not interpret tool-wide progress as live GitHub truth. Preserve existing read-only `AUD`. |
| `apatch_lib/gitutil.py`, `apatch_lib/github.py` | Add only bounded read-only helpers actually needed for exact branch, revision, index and PR identity. No additional mutation retry. |
| `tests/test_status.py`, `tests/test_audit.py`, `tests/test_github.py` | Cover each scenario, explicit ZIP overriding a different cached selection, stale `superseded_by` as weak evidence, detached HEAD, stale state, unexpected remote URL, missing PR data, matched/mismatched manual commit, and no-write snapshot invariants. |

Algorithm:

```python
def classify_context(selection, target_repository, optional_remote):
    local = inspect_git_branch_head_index_worktree()
    recorded = read_sessions_patches_runs_cache_and_history()
    evidence = compare_recorded_claims_with_local_facts(recorded, local)
    if publication_is_relevant:
        evidence += verify_unique_remote_branch_and_exact_pr_revision()
    if any_required_fact_conflicts(evidence):
        return ContextReport("BLOCKED", evidence)
    if not uniquely_selectable_session(evidence):
        return ContextReport("AMBIGUOUS", evidence)
    return ContextReport(classify_verified_scenario(evidence), evidence)
```

**Recovery:** network failure produces local diagnosis plus `UNKNOWN` remote facts; no implied permission to publish. **Acceptance:** SUB-003 FS-02, FS-12, FS-13, FS-18, FS-19. Repeated inspection MUST preserve all target bytes and refs.

## FS-03 — Continue after commit/push while retaining existing follow-up

**Objective:** Allow independent later ZIPs on the same unfinished feature session, including a predecessor already committed/pushed, subject to exact ancestry/remote/overlap guards. **Dependencies:** FS-02. **Non-goals:** automatic PR merge, replay of an existing ZIP, changing `handoffSeq` order.

| Path | Work |
| --- | --- |
| `apatch_lib/loose.py` | Keep `assert_followup_selection` for legacy calls; add a separately invoked session-aware guard for high-level continuation. Require verified target branch, HEAD ancestry, remote identity and safe archive overlap. |
| `apatch_lib/branch_patch.py` | Reuse base-first `APL → BRN` for a new feature; never create a branch for a verified continuation. |
| `apatch_lib/patch.py` | Reuse safe ZIP inspection, digest, extraction and deletions. Define overlap decision contract: no implied unattended overwrite of manually modified content. |
| `apatch_lib/workflow.py`, `apatch_lib/session.py` | Associate successful new ZIP with the active session, retaining previous commits and patches as distinct facts. |
| `apatch.py` | Route session-aware continuation only through its eventual explicit goal path; do not change direct `followup=true` semantics during this stage. |
| `tests/test_handoffs.py`, `tests/test_sequences.py`, `tests/test_branches.py` | Separate ZIP after commit; after push/open PR; no extra BRN; previous patch reapply refused; explicit reselect of an already-applied follow-up distinguished from new `APL`; branch drift; remote drift; overlap decline; multiple distinct ZIPs; manual changes intact. |

Illustrative flow:

```python
scenario = context.require_verified_active_session(new_zip)
assert_zip_new_and_order_valid(new_zip)
assert_current_branch_and_remote_match(scenario)
assert_prior_commit_ancestry_and_pr_revision_sane(scenario)
inspect_collisions_without_overwriting()
if collisions_need_decision:
    return waiting_for_user_before_mutation()
apply_and_record_one_new_patch()
session.append_patch_only_after_application_success()
invalidate_stale_check_and_publication_revision_evidence()
```

An existing PR remains tied to its historical source SHA until a new commit/push is independently verified. **Recovery:** failed `APL` leaves earlier feature branch commits, PR and user edits untouched. **Acceptance:** SUB-003 FS-03–06, FS-09, FS-11, FS-15, FS-17.

## FS-04 — Verification fingerprints, explicit commit scope and unattended safety

**Objective:** Make automatic `CMT` safe when a human and ZIPs both modify the worktree. **Dependencies:** FS-03. **Non-goals:** automatically selecting unknown files or weakening interactive LOOSE behavior.

| Path | Work |
| --- | --- |
| `apatch_lib/gitutil.py` | Expose stable tracked/index/untracked byte fingerprint and exact path inventory, retaining existing `worktree_fingerprint` semantics for legacy paths. |
| `apatch_lib/loose.py` | Add a separate guarded commit path used only by the goal planner; direct `commit()` remains compatible. Do not use indiscriminate `git add -A` when scope is ambiguous. |
| `apatch_lib/context.py`, `apatch_lib/session.py` | Track patch footprints, pre-existing staged files, explicitly accepted manual paths and unclassified files. Guard exact branch/head/fingerprint and check configuration revision before committing. |
| `apatch_lib/presentation/execution.py` | Show `NEEDS_VERIFICATION` and `WAITING_FOR_USER` with safe continuation rather than generic `NO_OP`. |
| `tests/test_handoffs.py`, `tests/test_modes.py`, `tests/test_safety.py`, `tests/test_sequences.py` | Worktree mutations during tests, formatter stabilization, deleted/untracked files, unrelated staged changes, mismatched branch, skipApproves=true, scope drift between check and commit, interrupted staging. |
| `docs/SECURITY.md`, `docs/USAGE.md` | Document planner-only stricter gates when actually implemented. |

Minimal safe sequence:

```python
scope = derive_session_owned_paths_and_explicit_manual_acceptance()
if scope.contains_unclassified_paths_or_collisions:
    stop_without_staging(scope.explanation)
checked = latest_check_evidence()
if checked != current_fingerprint_head_branch_and_check_policy:
    stop_with_recheck_guidance()
stage_only_authorized_paths_without_resetting_other_index_entries()
if staged_snapshot_is_not_exactly_authorized:
    stop_before_commit_and_preserve_index()
commit_with_selected_handoff_message_and_atomic_evidence_update()
```

The exact explicit-scope CLI syntax is an **open design gate**; FS-04 must define it before enabling unattended CMT. A project-configured, bounded formatter recheck may be added only after an independently verified stable-result test. **Recovery:** no automatic overwrite, reset, cleanup or unstaging of user-owned paths. **Acceptance:** SUB-003 FS-07–11, FS-15.

## FS-05 — Planner interface, local goal execution and console decisions

**Objective:** Introduce a validated, evidence-driven `goal` interface with read-only preview and safe local plans. **Dependencies:** FS-02 and FS-04. **Non-goals:** remote PR mutation until FS-06, changing direct `opSeq` semantics.

| Path | Work |
| --- | --- |
| `apatch_lib/planner.py` (**new**) | Immutable `ExecutionPlan`, explicit goal/intent validation, plan construction, dependency and guard ordering, per-action live reevaluation and bounded retry budget. |
| `apatch.py` | Extend `normalize_legacy_arguments`, parser and `main` with `goal`, `intent`, `planOnly`; validate mutual exclusion with `op`/`opSeq`, LOOSE-only initial scope and handoff requirements before any side effects. |
| `apatch_lib/sequence.py` | Reuse the existing action executor only where safe, without altering its exact `opSeq` behavior or `handoffSeq` preflight. Planner chooses the next step separately. |
| `apatch_lib/workflow.py` | Dispatch the selected existing actions and journal operation outcomes; the planner records plan-level correlation without duplicating per-action runs. |
| `apatch_lib/console.py`, `apatch_lib/presentation/execution.py` | Structured CONTEXT/PLAN/GUARDS/EXECUTION/RECOVERY with bounded paths and ANSI-free non-TTY presentation. Explicitly label an already-applied ZIP as *selected, not reapplied*; provide stable failure codes for wrong ZIP/checkpoint, changed digest, missing check executable, stale branch/check fingerprint and ambiguous session. Show short safe `CHK,STS` recovery and any longer sequence's commit/push/PR/merge effects. |
| `tests/test_config_cli.py`, `tests/test_sequences.py`, `tests/test_status.py`, `tests/test_operation_journal.py` | Parse conflicts, planOnly full immutability, repeated explicit ZIP selection, already-satisfied branches, missing/unexecutable `checks` commands with project-root diagnostics, ambiguous sessions, stable checks, interrupted local execution, formatted stdout/color suppression and output/exit-code contracts. |

Planner pseudocode:

```python
def execute_goal(goal, intent, selected_zip=None, preview=False):
    context = reconcile_and_classify()
    plan = build_steps_from_verified_context(context, goal, intent, selected_zip)
    present_structured_plan(plan)
    if preview or plan.blockers:
        return preview_result_or_actionable_blocker()
    for step in plan.steps:
        refreshed = reconcile_before_step(step)
        if refreshed.blocked_or_ambiguous:
            return stopped_with_recovery(refreshed)
        if refreshed.proves_satisfied(step):
            record_skip_reason_without_fabricating_action_success(step)
            continue
        run_existing_guarded_action(step)
        reconcile_after_step(step)
    return verify_requested_goal_from_live_evidence(goal)
```

Start with `goal=CHECKED` and `goal=COMMITTED`; gate `PUSHED` on proven remote checks and `MERGED` on FS-06. Never infer that any canonical checks passed solely from a prior phase or tool-wide progress event. **Acceptance:** SUB-003 FS-01/02 local portions, FS-06–12, FS-15–20.

## FS-06 — Guarded publication, exact PR revision, merge and sync

**Objective:** Complete `goal=PUSHED|PR_CREATED|MERGED` only after independent live proof of GitHub and Git safety. **Dependencies:** FS-05 and stable FS-04 commit scope. **Non-goals:** force-push, background approval, auto-retry of uncertain mutation.

| Path | Work |
| --- | --- |
| `apatch_lib/planner.py` | Verify publication-specific preconditions at every transition; `MERGED` completion includes `SYN` and verified local base synchronization. |
| `apatch_lib/github.py` | Reuse current exact PR source SHA/base/review/CI/mergeability checks and read retries. Never automatically replay `gh pr create` or `gh pr merge` after timeout. |
| `apatch_lib/force.py`, `apatch_lib/loose.py` | Use guarded existing PR/MRG/SYN paths; ensure journal and session association update only on proven live result. Do not change FORCE into force push. |
| `apatch_lib/branch_guard.py`, `apatch_lib/branch_patch.py` | Reuse non-configurable outstanding-feature preflight and fast-forward synchronization. |
| `apatch_lib/context.py`, `apatch_lib/session.py` | Track historical PR revisions separately from the newly pushed HEAD; reconcile manually pushed/merged outcomes without overwriting earlier evidence. |
| `tests/test_github.py`, `tests/test_branches.py`, `tests/test_modes.py`, `tests/test_operation_journal.py` | Open PR updated by new SHA, stale merged PR, same branch reused, approvals disabled by project policy, CI required or disabled, fast-forward/no-FF, transient reads, uncertain mutation, separately retryable SYN. |
| `README.md`, `docs/USAGE.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md` | Enable examples only after implementation and tests; distinguish explicit goal authorization from prompt skipping. |

Publication algorithm:

```python
assert_exact_verified_feature_commit_and_target_remote()
push_with_existing_fast_forward_guard_if_needed()
assert_remote_head_equals_verified_commit()
pr = read_or_create_unique_matching_pr_without_mutation_retry()
assert_pr_head_base_and_commit_identity(pr)
assert_configured_review_ci_and_server_policy()
merge_once_then_verify_exact_pr_revision()
if_merge_outcome_unknown_stop_for_explicit_reconciliation()
sync_base_fast_forward_only()
assert_local_base_matches_verified_merged_remote()
```

**Recovery:** an indeterminate `PR` or `MRG` marks the plan unresolved; show bounded read-only diagnostic steps, never recreate the PR or reissue merge without independent proof. An already merged PR can resume at `SYN`. **Acceptance:** SUB-003 FS-01, FS-05, FS-11–16, FS-19–20.

## 2. Release gates and documentation maintenance

1. Confirm pending design choices from SUB-003 §10 in a separately approved specification revision before implementing affected behavior; do not choose a permissive default in code.
2. Run focused cases plus `sh ./run_tests.sh` and `sh ./run_rare_checks.sh` after each stage. Capture counts, failed tests, dependency restrictions and exact verified Git revisions in the handoff report.
3. Verify Windows/macOS-specific semantics separately (paths, Git quoting, terminal colors, subprocess behavior). Linux-only success must be labeled Linux-only.
4. Run a regression matrix for legacy explicit JSON, numeric `2 [BAP]`, LOOSE/STRICT/FORCE, `followup=true`, `handoffSeq`, single-`op`, deterministic `opSeq`, retries, checked bytes and optional offline `AUD`.
5. All examples in current-facing `USAGE.md` and `README.md` remain strictly **implemented-only**. Keep proposed CLI syntax and stage-by-stage acceptance evidence in SUB-003/this plan until each related stage ships.
6. A failed stage is recovered by preserving user changes and original checkpoints, inspecting `STS`/`AUD`, and generating a new corrective patch on the appropriate feature branch. Never reset, force-push, purge unknown history or manually assume a GitHub merge.
