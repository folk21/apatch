# APATCH-PLAN-005 — Incremental Architectural Simplification

**Status:** Advisory GENSPEC implementation plan. AS-01 and AS-02 have separately prepared implementation candidates; AS-03–AS-07 remain proposed. Neither candidate is assumed installed. This document alone does not authorize production refactoring.

**Normative owner:** [APATCH-SUB-005](../active/subspecs/subspec-05-architectural-simplification.md). **Related owners:** [SUB-001](../active/subspecs/subspec-01-workflow-control.md), [SUB-002](../active/subspecs/subspec-02-state-history-audit.md), [SUB-003](../active/subspecs/subspec-03-feature-session-planning.md), and [SUB-004](../active/subspecs/subspec-04-operational-workflows.md).

**Inspected baseline:** reconstructed project from user-provided `apatch_files.txt`, main SHA `9f256d786d29d4121ea0116758af85a903d9636a` as of 2026-10-26 17:21 UTC, with separate unverified WM-01, WM-02 and FS-00 candidates. Implementation MUST re-read the installed source and state/tests before editing. A stage that is already implemented at that later HEAD SHALL become verification-only; do not introduce redundant replacement modules.

## 1. Incremental execution strategy

Use **one focused, self-contained ZIP per stage**, with tests and a new inspection checkpoint after each integration. Retain existing worktrees, applied history and GitHub state; no branch/PR/merge actions in a documentation-only GENSPEC deliverable. The developer selects and authorizes each later DEFAULT implementation stage independently.

| Stage | Objective | Prerequisite | Principal verification |
| --- | --- | --- | --- |
| **AS-01** | Characterization and defects-at-seams regression tests | Current source reinspection | Reproduce `STS` advice mismatch and malformed state/PR handling without altering production policy |
| **AS-02** | Typed and validated persisted/remote boundaries | AS-01 fixtures | Backward/forward compatible state, config and `gh` decoding |
| **AS-03** | Explicit action results; isolate presentation and cancellation | AS-01, AS-02 typed models | Same result across single/menu/sequence, accurate journals, no unsafe remote replay |
| **AS-04** | Small CLI entry point and one application dispatcher | AS-03 | CLI grammar/ZIP selection/read-only operations and all existing mode aliases |
| **AS-05** | Centralized tested action applicability and next-step advice | AS-03, AS-04; session planner compatibility gate | `STS`/executor agreement, existing LOOSE/STRICT/FORCE safety matrix |
| **AS-06** | Pure read-only reconciliation and narrow audit collectors | AS-02; independent of AS-04/AS-05 once DTOs stable | Stable audit findings, optional offline/remote failures, no writes |
| **AS-07** | Incremental Ruff/types, fixture cleanup and documentation alignment | Stages with stabilized boundaries; lint baseline separately negotiated | Non-mutating style checks, scoped type checks, all suites |

**Recommended merge order:** AS-01 → AS-02 → AS-03 → AS-04 → AS-05; AS-06 may follow AS-02 in parallel only when its interfaces are stable; AS-07 can introduce tooling early but may not turn a large formatting diff into a hidden prerequisite. In particular, SUB-004 WM-03–WM-05 SHOULD use the post-AS-03 `ActionResult`/dispatcher contract rather than writing a second operation executor. SUB-003 FS-00R/FS-01 context work may supply the verified session resolver first; AS-04/AS-05 MUST integrate it rather than reinterpret applied-history semantics.

### Stage-wide invariants

1. Reconfirm the original source and run `git status` before editing; never overwrite independent developer work or assume a previous ZIP was merged. Create a new feature branch only under the existing branch guard.
2. Preserve numeric `0..11`, all legacy parser forms, base-branch precedence, YAML schema-v1, ZIP schema-v1, state v1/v2, records and mode semantics. Only a separately documented bug fix may change observable advice or a controlled error category.
3. Treat Git refs, index, working-tree bytes, state/journals and GitHub PRs as separately committed effects. Record the exact evidence and safe continuation of every stopped stage. No destructive rollback or automatic remote mutation replay.
4. Add unit tests around pure decisions plus temporary local Git repositories and mocked `gh`. Do not test against a real developer GitHub remote or persistent user repository.
5. For every implementation ZIP: run focused tests; `sh ./run_tests.sh`; `sh ./run_rare_checks.sh`; `sh -n` for changed shell files; source compilation/import validation; packaging inventory and SHA-256. Explicitly distinguish tests that could not run, platform differences and documentation-only checks.
6. Follow an **expand → migrate consumers → contract** pattern for signatures, journal values and config schema. In each stage, retain old adapters until all production callers and tests have been switched. Never change persistence semantics solely to make typing easier.

## 2. Target boundaries and responsibilities

The following is a **candidate layout**, not a demand to create every file. Reuse existing files if a focused extraction would remain readable; the goal is fewer interdependent conditionals and less duplicated policy.

```text
apatch.py                         # Thin main() and backward-compatible argument entry point
apatch_lib/
  cli_request.py                 # Proposed validated CLI request/selection intent
  application.py                 # Proposed action coordinator and explicit outcome mapping
  core/
    actions.py                   # Existing immutable numeric action IDs
    enums.py                     # Existing phase/outcome enums
    contracts.py                 # Proposed ActionResult/WorkflowContext DTOs
  workflow.py                    # Existing workflow data and lifecycle adapter, gradually thinner
  presentation/execution.py      # Console-facing presenter only after AS-03
  status.py                      # Pure recommendation using shared precondition facts
  state.py                       # Validated state format and atomic storage
  operation_events.py            # Existing journal persistence contract
  github.py                      # Validated PR evidence and existing safe GH operations
  reconciliation.py              # Read-only audit facade, typed report
  audit_collectors.py           # Proposed bounded read-only evidence collectors
  audit_rules.py                # Proposed pure reconciliation rules
  loose.py, force.py             # Preserved mode-specific action/recovery policies
  console.py                     # User-visible output, redaction, optional color
```

**Rule:** avoid reciprocal imports between coordinator and adapters, avoid a second `Workflow` ownership model, and do not move all methods at once. Share immutable DTOs, not a mutable global application context. A pure `if` with clear input and output is preferable to a dynamic registry that hides the condition.

## AS-01 — Baseline characterization and controlled defect cases

**Status:** Test implementation candidate; integration and release unverified. **Purpose:** stop the refactor from changing operational semantics accidentally. **No production rewrite** in this stage unless a tiny independent defect fix is separately approved.

| Exact path / function | Ordered work |
| --- | --- |
| `apatch.py:main()`, `normalize_arguments()`, `resolve_selected_handoff()` | Inventory accepted forms: ZIP/no ZIP, `op`, `opSeq`, `handoffSeq`, `followup=true`, menu, `STS`, `AUD`, `info=PROGRESS`, LOOSE/STRICT/FORCE. Record whether the installed HEAD includes FS-00R and future macros. |
| `apatch_lib/presentation/execution.py:OperationPresentation.interactive()`; `apatch_lib/workflow.py:Workflow.interactive()` and `options()` | Characterize every path returning `NO_OP`, inferred `SUCCESS`, verified satisfaction, cancellation, blocked `Abort`, check-change and `RemoteOutcomeUnknown`; record the journal/progress side effects. |
| `apatch_lib/status.py:recommend_next_action()` | Reproduce the observed mismatch: new ZIP/phase `new` on configured `main` suggests `BRN` despite ZIP-first admission requiring `APL`; add phase/branch/mode table tests. |
| `apatch_lib/state.py:_upgrade_and_validate()`; `apatch_lib/workflow.py:Workflow.__init__()` | Add malformed nested state `{"workflows":{"bad":[]}}`, missing identity, wrong field types, unknown forward-compatible fields and historical v1 cases. Assert controlled errors are the desired eventual behavior; baseline currently fails selected negative cases. |
| `apatch_lib/github.py:pr_list()`, `pr_details()`; `apatch_lib/reconciliation.py:_remote_snapshot()` | Add mocked malformed JSON, object instead of list, invalid PR item, missing `headRefName`, null `headRefOid`, oversized strings, 504/timeout, conflicting repo/base/head. No live GitHub access. |
| `tests/test_config_cli.py`, `tests/test_sequences.py`, `tests/test_handoffs.py`, `tests/test_status.py`, `tests/test_github.py`, `tests/test_history.py`, `tests/test_audit.py`, `tests/test_operation_journal.py` | Add table-driven characterization cases in existing suites; mark genuinely new stricter desired expectations as expected failures or put them in a separate explicit RED test selection until AS-02/AS-05 fixes land. Do not commit permanently failing canonical tests. |
| `docs/ARCHITECTURE.md` | Capture existing verified module boundaries and any actual source drift before modifying the proposed ownership map. |

Review checklist before refactoring: all expected **green** tests pass on the unchanged baseline; known **red** behavior has a reproducible fixture and a stage owner; every material public CLI contract has at least one positive and one negative test. Record regular/rare test durations and Python/OS information. Do not turn discovered failures into silent skips.

**AS-01 candidate evidence:** `tests/test_architecture_characterization.py` adds 14 focused checks. Ten characterize current successful behavior: status phase recommendations and conflict stops; ZIP-first pending-branch advice; legacy-state read/write preservation; malformed top-level state rejection; PR filtering; bounded read-only retry versus permanent failure; no replay of uncertain PR mutation; and cancellation that leaves worktree/ZIP history unchanged. Four deliberately strict assertions use `@unittest.expectedFailure` against confirmed baseline defects: new ZIP on the base suggesting BRN before APL (**AS-05**), nested non-mapping workflow not rejected (**AS-02**), non-list `gh pr list` JSON not mapped to `Abort` (**AS-02**), and malformed `gh pr view` JSON not mapped to `Abort` (**AS-02**). The regular suite includes this module; these expected failures **do not satisfy** AR-05/AR-06/AR-07 and SHALL become normal green regressions when fixed. No production module was modified by the test candidate.

**Acceptance contribution:** AR-03–AR-08, AR-12–AR-13 (baseline). **Failure/recovery:** if the inspected source diverges or the existing suite fails, stop and update the inventory; do not transplant code against the stale snapshot.

## AS-02 — Typed models and validated external boundaries

**Status:** Implementation candidate prepared; integration and release unverified. **Dependencies:** AS-01. **Non-goals:** rewriting journal history, changing CLI grammar, mandatory Pydantic, or making remote retries.

| Exact path / function | Ordered work |
| --- | --- |
| `apatch_lib/core/contracts.py` (proposed), `apatch_lib/model.py:Config`, `Handoff` | Introduce narrow, frozen DTOs for effective configuration, validated patch/session identity and external PR fields, preserving existing `Config` construction and `Handoff` equality/attribute semantics. Add parameter/return annotations to touched functions. |
| `apatch_lib/state.py:_upgrade_and_validate()`, `read_state_snapshot()`, `locked_state()`, `save()` | Parse raw `object`/recursive `JsonValue`, validate top-level and each workflow record, then expose a typed read view. Preserve legacy v1 upgrade on authorized writes only; keep unknown compatible keys when serializing. Check filesize, symlink and atomic-write boundaries before decoding. |
| `apatch_lib/workflow.py:Workflow.__init__()`, `persist()`, `inspect_previous_cycles()` | Replace unguarded `record.get(...)` assumptions with validated record access, without rewriting unrelated historical fields. Test state read during `STS` and `AUD`. |
| `apatch_lib/github.py:pr_list()`, `pr_details()`, `_record_current_pr()` | Introduce `decode_pr_list(raw: str, expected_repo: ...)` and `decode_pr_details(raw: str, ...)` or equivalent. Validate each PR item's required/optional types, number, head/base refs, head OID and merged state before comparing revisions. Preserve command timeout and no-mutation-on-corrupt-response behavior. |
| `apatch_lib/reconciliation.py:_remote_snapshot()` | Decode remote JSON through the same trusted PR-boundary helpers, subject to audit's own list limit and read-only contract; do not treat malformed/partial JSON as an empty PR list. |
| `apatch_lib/model.py:load_project_config()`, `apatch_lib/patch.py:inspect()` | Refine type annotations and validation objects at YAML/ZIP boundaries without broadening accepted paths or changing the project's opt-in check-command policy. |
| `tests/test_history.py`, `tests/test_handoffs.py`, `tests/test_github.py`, `tests/test_audit.py`, `tests/test_config_cli.py` | Add state v1/v2 plus mixed unknown fields, bad record types, PR JSON shape/type, large/unsafe values, wrong repo/base/head and no-mutation assertions. |

Suggested parsing pattern (illustrative; choose concrete types based on actual schema):

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PullRequestInfo:
    number: int
    state: str
    head_ref_name: str
    base_ref_name: str
    head_oid: str | None


def decode_pr_list(raw: str) -> tuple[PullRequestInfo, ...]:
    value: object = parse_bounded_json(raw)
    rows = expect_list(value, source="GitHub PR list")
    return tuple(decode_pr_item(row) for row in rows)
```

`parse_bounded_json`, `expect_list`, and `decode_pr_item` are **proposed helpers**, not existing APIs. Capture unknown on-disk state fields separately from typed known fields; never coerce a number into a branch name or a dictionary into an empty list.

**AS-02 candidate evidence:** `apatch_lib/core/contracts.py` adds typed workflow and PR JSON views without a new dependency. `state.py` validates known workflow fields before handing records to the coordinator, preserving schema-v1 read purity and unknown keys. `github.py` bounds/parses PR lists and detail objects, including repository, PR number, head revision, nullable evidence and check-rollup shape. `reconciliation.py` reuses the same decoder before remote audit processing. Existing public JSON mapping shapes and timeouts remain unchanged. Three AS-01 expected-failure cases are now ordinary passing tests; the status-advice case remains AS-05. Added corruption, round-trip, Unicode, list, identity, and audit seam tests. Full regression results and source drift must be rechecked when integrated.

**Acceptance:** AR-02, AR-05, AR-06, AR-08, AR-10 (candidate evidence; no acceptance implied). **Failure/recovery:** invalid persisted/remote data aborts before mutations, reports the source and field class without echoing secrets, leaves original bytes untouched; a missing optional source remains distinguishable from corruption.

## AS-03 — Explicit outcomes and separation of action execution from presentation

**Status:** Proposed. **Dependencies:** AS-01/AS-02. **Non-goals:** a new workflow DSL, altering exact sequence order, inventing new GitHub retry behavior.

| Exact path / function | Ordered work |
| --- | --- |
| `apatch_lib/core/enums.py:OperationOutcome`, `apatch_lib/operation_events.py:RunOutcome`, proposed `core/contracts.py:ActionResult` | Define typed outcome/evidence/result fields and one explicit compatibility mapping for journal `SUCCEEDED`, `NO_OP`, `FAILED`, `CANCELLED`, `INTERRUPTED`, `INDETERMINATE` and progress names. Decide `BLOCKED` representation before extending schemas. |
| `apatch_lib/loose.py:LooseActions.*`, `apatch_lib/force.py:ForceActions.*`, `apatch_lib/branch_patch.py:BranchPatchActions.*`, `apatch_lib/workflow.py:Workflow.*` | Migrate one action at a time to return an explicit result/effect proof; retain existing safety checks and mode policies. `verify()` success with unchanged bytes is still `SUCCESS` if fresh check evidence proves it. A declined confirmation is `CANCELLED`, not guessed from an unchanged branch. |
| `apatch_lib/gitutil.py:confirm()`, `clear_confirmation_declined()`, `confirmation_was_declined()` | Replace ambient confirmation state with explicit `ConfirmationDecision`/typed cancellation only after all action call sites have migrated. Retain wrapper compatibility during transition. |
| `apatch_lib/presentation/execution.py:OperationPresentation.interactive()`, `_record_progress()` | Stop invoking individual mode mutations and inferring results by worktree delta. Render a completed `ActionResult`, report preservation/recovery and call the journal/progress mapping. Keep `print()`/console output where it is the intended user interface. |
| `apatch_lib/workflow.py:Workflow.interactive()`, `_verified_run_facts()`, `apatch_lib/sequence.py:execute_sequence()` | Move sequence continuation/stop rules to a single application executor. `NO_OP` stops unless proven satisfied, `CANCELLED` stops, and `UNKNOWN_REMOTE_RESULT` always stops remote mutation. Keep operation IDs and correlation IDs. |
| `tests/test_sequences.py`, `tests/test_modes.py`, `tests/test_operation_journal.py`, `tests/test_progress.py`, `tests/test_github.py` | Verify result/journal/progress alignment, repeat verified CHK, no-op vs already-satisfied, wrong checkout, cancellation, failed checks, worktree-changed, interrupted state save and indeterminate PR. |

Suggested application boundary:

```python
def execute_action(request: OperationRequest, context: WorkflowContext) -> ActionResult:
    descriptor = action_by_number(request.action_number)
    preconditions = evaluate_live_preconditions(descriptor, context)
    if preconditions.is_blocked:
        return ActionResult.blocked(descriptor, preconditions.reason)
    if preconditions.is_proven_satisfied:
        return ActionResult.already_satisfied(descriptor, preconditions.evidence)
    return descriptor.execute(context)
```

This is **conceptual pseudocode**; do not create `ActionResult.blocked` or the registry mechanically if simpler explicit functions suffice. In particular, no broad catch of `Exception` can suppress failed GitHub writes or conflate them with a cancelled prompt.

**Acceptance:** AR-01, AR-03, AR-04, AR-08, AR-10, AR-13. **Failure/recovery:** if external mutation succeeded but journaling failed, re-read live state at resume; never repeat the side effect merely because no completion event was recorded. Do not delete an unresolved `STARTED` record.

## AS-04 — Split CLI parsing, resolution and application coordination

**Status:** Proposed. **Dependencies:** AS-03. **Non-goals:** introducing already-unimplemented `goal=`/macro syntax, weakening ZIP admission, or changing `followup=true` semantics.

| Exact path / function | Ordered work |
| --- | --- |
| `apatch.py:main()`, `normalize_arguments()`, `parse_operation()` and `parse_operation_sequence()` | Extract construction and validation of `argparse` request into a small tested parser module (`cli_request.py` proposed). Keep historical `key=value` normalization, mode/defaults, option incompatibilities and friendly `--help`. |
| `apatch.py:resolve_selected_handoff()`, `resolve_handoff_path()`, `resolve_sequence_zip_names()` | Introduce a read-only selection resolver returning explicit `NEW_ZIP`, `APPLIED_ZIP`, `CACHED_WORKFLOW`, `LEGACY_JSON` or `CONFLICT` with evidence and required next step. Delegate actual already-applied ZIP constraints to SUB-003's resolved session model when installed; avoid duplicating its digest/history guards. |
| `apatch.py:show_status_with_progress()`, `show_audit_with_activity()` | Retain read-only fast paths before any workflow/state locks or installation side effects; optional tool-wide progress remains advisory. |
| `apatch_lib/application.py` (proposed), `apatch_lib/workflow.py:Workflow.__init__()` | Centralize bootstrap and one execution call for `op`, menu and `opSeq`, passing immutable request/context. Do not instantiate alternate workflows for one ZIP selection just to work around the selection gate. |
| `apatch_lib/params_cache.py`, `apatch_lib/state.py:locked_state()`, `apatch_lib/sequence.py:execute_sequence()` | Keep existing state-lock scope, cache write-after-confirmed-success, sequence order and multi-ZIP handoff selection atomic enough for current contract; do not create locks for read-only dispatch. |
| `tests/test_config_cli.py`, `tests/test_handoffs.py`, `tests/test_sequences.py`, `tests/test_audit.py`, `tests/test_progress.py` | Contract-test every option combination, detached/wrong branch, different archive digest, read-only/no-repository progress, interactive menu, legacy JSON, repeated ZIP selection, multi-ZIP application and failed cache write. |

Execution sketch:

```python
def main() -> int:
    try:
        request = parse_request()
        selection = resolve_request(request)
        result = execute_or_inspect(request, selection)
        render_result(result)
        return exit_code_for(result)
    except ExpectedApatchError as error:
        render_error(error)
        return 2
```

Keep Python's `if __name__ == "__main__":` entry-point guard. Names in this sketch are illustrative, not installed APIs. Preserve `KeyboardInterrupt` semantics and logging redaction; never `except Exception: return 0`.

**Acceptance:** AR-01, AR-03–AR-04, AR-08, AR-13. **Failure/recovery:** parsing/resolution failures leave ZIP bytes, cache, runtime state and Git refs untouched; if handoff resolution is ambiguous, show a concrete safe `STS`/explicit selection command rather than guessing.

## AS-05 — One tested precondition source for executor and `STS`

**Status:** Proposed. **Dependencies:** AS-03, AS-04 and alignment with SUB-003 context resolver. **Non-goals:** auto-performing a recommended action or merging LOOSE/STRICT/FORCE into one permissive policy.

| Exact path / function | Ordered work |
| --- | --- |
| `apatch_lib/workflow.py:Workflow.options()`, `assert_patch_identity()`, `assert_expected_paths()` | Express availability with small named precondition evaluators and reasons, not a 90-line chain of mixed string phases and mode-specific branches. Keep each mode's original guard. |
| `apatch_lib/status.py:recommend_next_action()`, `inspect_patch()` | Derive recommendation from safe action applicability and current evidence, not a phase-only table. Preserve offline read-only behavior. Fix new self-contained ZIP on clean base: `APL` before `BRN`; after ZIP-first extraction, `BRN`; on conflict, no unsafe suggestion. |
| `apatch_lib/branch_guard.py`, `apatch_lib/branch_patch.py`, `apatch_lib/loose.py:assert_followup_selection()`, `apatch_lib/force.py` | Share only mandatory integrity checks: remote identity, archive ordering/overwrite, branch creation, fast-forward and review/CI gates. Keep strict policy and force-recovery behavior explicit. |
| `apatch_lib/sequence.py:execute_sequence()` | Use AS-03 explicit results and SUB-003's verified last-applied/session condition for a requested repeated `APL`/`BRN`. Evaluate after each completed step and preserve exact sequence positions. |
| `tests/test_status.py`, `tests/test_branches.py`, `tests/test_safety.py`, `tests/test_modes.py`, `tests/test_handoffs.py`, `tests/test_sequences.py` | Build a cross-product matrix of phase, branch, mode, handoff source, dirty worktree, remote head, prior patch state and explicit skip approvals. Assert `STS` never recommends an immediately forbidden step without explaining its prerequisite. |

Example decision table (normative semantics remain in SUB-003/SUB-005):

| Evidence | Recommended next atomic step | Mutation permission |
| --- | --- | --- |
| New valid self-contained ZIP on configured clean base | `APL` | Only after existing ZIP and branch-safety guards |
| Same ZIP just safely applied on base (ZIP-first) | `BRN` | Only if branch creation guard passes |
| Last applied matching ZIP, current verified feature branch | `CHK` or next eligible step | Repeated `APL`/`BRN` may be `ALREADY_SATISFIED` only under SUB-003 proof |
| Older non-last applied ZIP or archive digest conflict | Reconcile history | No unattended replay or skip |
| LOOSE manual edits after `CHK` | `CHK` again | Never reuse stale checked fingerprint |
| Remote PR outcome indeterminate | Read-only PR inspection | No second mutation without exact proof |

**Acceptance:** AR-03, AR-07–AR-08, AR-10, AR-13. **Failure/recovery:** if a suggested action is blocked after a concurrent repository change, the live executor blocks normally; never apply a stale read-only recommendation as a waiver. No automatic checkout or rewrite on mismatch.

## AS-06 — Decompose the read-only audit into evidence and pure rules

**Status:** Proposed. **Dependencies:** AS-02; independent of AS-04/AS-05 after stable shared DTO boundaries. **Non-goals:** network scanning of every recorded project, state repairs, changing `AUD` into a mutation command.

| Exact path / function | Ordered work |
| --- | --- |
| `apatch_lib/reconciliation.py:_safe_text()`, `_created_entries()`, `_applied_entries()`, `_remote_snapshot()` | Move only cohesive readers to `audit_collectors.py` or retain short helpers where simpler. Continue O_NOFOLLOW, file size bounds, optional absence semantics, bounded Git subprocess and opt-in remote inspection. |
| `apatch_lib/reconciliation.py:audit_repository()` | Refactor into `collect_local_evidence`, `reconcile_patch_history`, `reconcile_workflow_records`, `reconcile_remote_evidence`, `build_audit_report` (names advisory). Each pure reconciler takes immutable parsed evidence and returns typed findings. |
| `apatch_lib/reconciliation.py:Finding`, `AuditReport`, `format_audit()` | Keep current format, finding codes, severity ordering, confidence labels and display truncation. Replace opaque heterogeneous `dict` fields with a dedicated DTO only where the existing renderer benefits. |
| `apatch.py:show_audit_with_activity()`, `apatch_lib/progress.py` | Preserve the installed WM-01 cross-project recorded activity preface; optional progress failure must not suppress a valid current-repository audit. Never write to progress from an `AUD` call. |
| `tests/test_audit.py`, `tests/test_history.py`, `tests/test_progress.py`, `tests/test_operation_journal.py` | Golden normalized audit summaries for missing/reordered/duplicate patches, v1 state, unresolved runs, malformed optional data, dirty Git, no remote, mocked contradictory remote, output limits and invariant filesystem/Git snapshots. |

Example pure decision boundary:

```python
def reconcile_patch_history(
    created: tuple[str, ...] | None,
    applied: tuple[AppliedPatchEntry, ...],
    workflows: tuple[WorkflowRecord, ...],
) -> tuple[Finding, ...]:
    ...
```

`AppliedPatchEntry` and `WorkflowRecord` are proposed typed imports; exact names may differ. Never call `gh` from a pure reconciler. **Acceptance:** AR-01–AR-02, AR-05–AR-06, AR-09, AR-13. **Failure/recovery:** repository audit must remain read-only even when local/remote evidence conflicts; optional remote unavailability is `UNKNOWN`, never an invented clean bill of health.

## AS-07 — Quality gates, incremental typing and documentation cleanup

**Status:** Proposed; can start only as a nonblocking baseline before earlier runtime refactors. **Non-goals:** blanket rewrites, auto-formatting canonical `CHK`, automatic workflow triggers or broad dependency upgrades.

| Exact path / function | Ordered work |
| --- | --- |
| `pyproject.toml` (new if justified) or minimal Ruff config | Pin documented minimum tool versions outside runtime `requirements.txt` where possible. Define `target-version = "py310"`, lint selected rules and formatting conventions. Gather full-repository findings; first gate applies only to chosen touched files or a measured clean subset. |
| `apatch_lib/core/`, `model.py`, `state.py`, `github.py`, `application.py` if created | Choose **one** type checker (mypy or Pyright), give precise first set of checked modules and explicit exclusions; shrink exclusions incrementally. Annotate every newly modified public method and all fresh DTOs. |
| `tests/_support.py` | Remove broad import/path hacks incrementally after module boundaries stabilize, preserving temporary repository factories and mocked-GitHub isolation. Ensure direct test execution and package-mode imports both still work. |
| `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, `docs/specs/README.md`, `docs/USAGE.md` | Document accepted boundaries and commands only after implementation; update link/status index, avoid static sub-spec counts and duplicate CLI contracts. Maintain clear `proposed` vs `installed` labels. |
| `run_tests.sh`, `run_rare_checks.sh`, `.github/workflows/` | Preserve existing regular/extended suites and manual-only CI. Adding a separate non-mutating lint/type command is preferable to silently changing every target repo's canonical CHK command. Automated PR triggers require separate developer authorization. |
| `tests/test_runner_scripts.py`, `tests/test_config_cli.py` | Test new quality-command invocation in an isolated subprocess, skip cleanly only where a genuinely optional executable is missing, and prove no formatting writes. |

Initial suggested commands (only after dependencies/config are introduced):

```bash
python3 -m ruff check apatch.py apatch_lib tests
python3 -m ruff format --check apatch.py apatch_lib tests
python3 -m mypy apatch_lib/core apatch_lib/state.py apatch_lib/github.py
```

The lint command scope above is a **target**, not a claim that all these files pass today; implement a staged scope with explicit exclusions if the baseline is not clean. Keep formatting checks distinct from source-changing `ruff format`. If Pyright is selected, replace mypy rather than carrying two unfinished configurations.

**Acceptance:** AR-02, AR-11–AR-14. **Failure/recovery:** unavailable optional static tools are reported as `NOT_RUN`, not success; a new required gate is enabled only after documented installation support and a clean controlled baseline.

## 3. Crash and interruption recovery matrix

Apply these checks to all stages touching side effects. This is a **forward-recovery guide**, not a fictitious multi-store transaction:

| Last confirmed effect before failure | Recovery evidence | Safe next action | Explicitly forbidden assumption |
| --- | --- | --- | --- |
| ZIP members extracted, state write incomplete | File fingerprint, archive digest, existing backups, applied journal, Git status | Inspect collisions; reconcile or resume only with proven applied identity | Re-extract, overwrite developer edits or assume no files changed |
| Applied-patch history updated, state checkpoint incomplete | Applied order plus current Git/ZIP evidence | Reconcile state under lock after explicit proof | Delete history entry to simulate rollback |
| State checkpoint saved, optional tool-wide progress write failed | Saved local workflow/operation run | Preserve operation outcome; warn that dashboard evidence is incomplete | Fail or repeat already completed Git action solely because progress is missing |
| Canonical checks exited zero but altered bytes | Pre/post index and worktree fingerprints | Preserve edits, invalidate check evidence, re-run full CHK under configured policy | Mark old bytes verified or auto-revert formatter changes |
| Commit created, journal update failed | Exact local HEAD/ancestry and intended commit scope | Adopt only verified same-revision commit | Create duplicate commit or reset HEAD |
| Push acknowledgement lost | Live remote branch SHA and local commit identity | Read-only reconcile; push only under independently proven safe fast-forward preconditions | Force-push or declare remote up to date from an old journal |
| PR create timed out/HTTP 504 | Repo/base/head/sha, live unique PR evidence | Read-only lookup; adopt exact match when authorized by SUB-004 WM-06 | Reissue `gh pr create` blindly or treat missing lookup as proof of no PR |
| PR merge acknowledgement lost | Live PR merge state, exact head/target revision and policy | Stop or adopt a fully verified merge | Reissue merge based only on timeout text or old merged phase |
| Merge confirmed, local `SYN` failed | Verified merged PR and configured base heads | Retry guarded `SYN` only after fresh evidence | Reset local base or claim the full lifecycle completed |

For every simulated crash point, tests SHALL ensure no unauthorized cleanup, branch rewrite, archive replay or second GitHub mutation. Read-only probes must remain free of project-state writes. Interrupted operation-run records remain inspectable and may be reconciled, never silently erased.

## 4. Review criteria and quantitative measures

At each stage record a compact before/after comparison for the changed hotspot:

- Line span, maximum structural nesting, branch/decision count and imported dependency fan-in. Report reduction **with reasoning**, not as a magic numerical goal.
- Number of sources from which an operation outcome can be inferred; target one authoritative result, independently checked by evidence.
- Public interface type coverage for touched modules; target full annotation for new/changed APIs. Do not count isolated raw JSON adapters as a failure merely for a documented narrow dynamic type.
- Mutation footprint: number of independently affected stores/refs per action, forward-recovery evidence and ability to resume safely.
- Testable boundaries: policy-unit tests, corrupt-state tests, mocked remote tests and temporary-Git integration regressions.
- Existing CLI compatibility: `op`, `opSeq`, `handoffSeq`, `followup`, cache, all modes, read-only STS/AUD/PROGRESS and success/error/unknown outcomes.

A refactor does not pass review merely because files are shorter or Ruff is green. If complexity is moved into an opaque registry or more scattered conditionals, treat it as an architectural regression.

## 5. Acceptance evidence per stage

Each future implementation response MUST state:

1. Exact source commit used, integrated previous candidate stages, changed paths and approved architectural stage.
2. Focused tests added, observed defects fixed, regular and extended test results and platform/tool gaps.
3. Precise persistence/schema/result compatibility changes, if any; example safe resume commands for stopped operations.
4. Which AS acceptance criteria and cross-spec dependencies are now verified, and which remain DRAFT.
5. Independent ZIP inventory, embedded handoff metadata and final SHA-256; no real GitHub action performed by the generator.

Only after integration and verification may the documentation index mark that particular stage as implemented. A completed ZIP artifact, a passing mock test or a user-confirmed plan does not establish installation or acceptance of the entire architecture sub-spec.
