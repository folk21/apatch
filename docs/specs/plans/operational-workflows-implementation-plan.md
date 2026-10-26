# APATCH-PLAN-004 — Operational Workflow Macros and Diagnostics

**Status:** Advisory plan. WM-01 and WM-02 each have implementation candidates in separate ZIP overlays; WM-03–WM-06 require subsequent implementation and independent acceptance. WM-06 is explicitly deferred.

**Normative owner:** [APATCH-SUB-004](../active/subspecs/subspec-04-operational-workflows.md). **Dependencies:** [SUB-001](../active/subspecs/subspec-01-workflow-control.md), [SUB-002](../active/subspecs/subspec-02-state-history-audit.md), and [SUB-003](../active/subspecs/subspec-03-feature-session-planning.md). The inspected source baseline is clean `main` commit `9f256d786d29d4121ea0116758af85a903d9636a` from the 2026-10-26 17:21 UTC project snapshot. This snapshot intentionally omits installation-local `apatch.conf` and target `.apatch/config.yaml` contents; verification uses an isolated sample config and does not package either private file.

## 1. Sequencing and cross-cutting rules

Implement each stage as one independently tested ZIP overlay. Preserve numeric IDs `0..11`, `opSeq`, legacy JSON, `handoffSeq`, existing cache and state, modes, and GitHub protection rules. Use LOOSE only for initial macro execution. Tool-wide progress is historical evidence; it must never authorize mutation. A macro stage that depends on SUB-003's unimplemented session context or explicit-scope requirements SHALL remain blocked until those dependencies are implemented and their compatibility tests pass. Do not substitute an unguarded fixed `opSeq` for the missing planner.

All stages require `sh ./run_tests.sh`, `sh ./run_rare_checks.sh` before handoff, focused tests, a safe ZIP inventory/digest, and disclosure of Linux-versus-macOS/Windows verification limits. The test harness uses temporary local Git repositories and bare remotes and mocks GitHub publication. Preserve developer modifications in dirty worktrees and never run remote writes outside synthetic tests.

## WM-01 — Recorded activity before project audit

**Status:** Implementation candidate. **Dependencies:** existing P0.5 progress and P1.2 audit. **Non-goals:** changing repository audit findings, refreshing all project remotes, recording read-only `AUD` invocations, or creating a dashboard database.

| Path | Ordered work |
| --- | --- |
| `apatch_lib/progress.py` | Reuse `ProgressStore.read_snapshot()` and `render_progress()`. Add a separately labelled `Last attempted [RECORDED]` and latest `SUCCESS` event per project. Return `none` when no recorded success exists. Do not change the journal schema, event order, or display limits. |
| `apatch.py` | Introduce `show_audit_with_activity(root, config, tool_dir, verify_remote=False)`. Read/render optional global progress before calling existing `audit_repository()/format_audit()`. Use this helper for direct `op=AUD/11`, singleton `opSeq=AUD/11`, and both interactive menu paths. Never create a workflow lock or contact remote GitHub for the dashboard. |
| `tests/test_audit.py` | Add synthetic interleaved events from two projects, a failed last attempt following a successful APL, an independently synced second project, read-only snapshots, malformed optional progress and direct/numeric/menu aliases. Preserve existing audit rejection of malformed target journals. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md` | Document only implemented read-only output and the distinction between recorded and verified remote facts. |

Algorithm:

```python
def show_audit_with_activity(root, config, tool_dir, verify_remote=False):
    try:
        snapshot = ProgressStore(tool_dir).read_snapshot()
        show(render_progress(snapshot, config.progress_global_limit,
                             config.progress_project_limit))
    except Abort as error:
        show_bounded_optional_progress_warning(error)
    show(format_audit(audit_repository(root, config, verify_remote=verify_remote)))
```

**Failure/recovery:** Optional progress corruption/symlinks cause a bounded warning, not loss of independent repository findings. Existing repository audit corruption still fails closed. All paths and progress data remain unchanged. **Acceptance:** SUB-004 WM-01–WM-03, WM-15. **Verification:** `python3 -B -m unittest tests.test_audit -v`, `sh ./run_tests.sh`, `sh ./run_rare_checks.sh`; ensure exact numeric, acronym and menu output parity.

## WM-02 — Per-project base-branch override

**Status:** Implementation candidate (separate WM-02 overlay). **Dependencies:** WM-01 for visible context; otherwise independent of macros. **Non-goals:** branch renaming, changing the remote URL, or autodetecting an alternative base from GitHub.

| Path | Ordered work |
| --- | --- |
| `apatch_lib/model.py` | Add `base_branch` to the allowed schema-v1 `.apatch/config.yaml` key set. Parse only a nonempty string. Validate syntactic branch-ref constraints using a tested Git-compatible helper, then `replace(global_config, base=value)` when present. Track the effective source (`project`/`global`) as additive metadata, preserving positional construction of existing `Config` callers. |
| `apatch_lib/branch_guard.py`, `apatch_lib/branch_patch.py`, `apatch_lib/loose.py`, `apatch_lib/force.py` | Confirm every branch preflight uses `config.base`; do not introduce hard-coded `main` during new branch application, reuse, commit, publication, or sync. Explicitly test matching remote base refs and no accidental fallback. |
| `apatch_lib/status.py`, `apatch_lib/reconciliation.py`, `apatch_lib/progress.py` | Where base-branch evidence is shown, label the effective configured value and source. Existing historical progress records retain their meaning; no migration rewrites. |
| `tests/test_config_cli.py`, `tests/test_branches.py`, `tests/test_github.py`, `tests/test_status.py` | Test `main` fallback, global `master`, per-project `develop`, nested release branch, invalid empty/null/boolean/nonsensical ref, absent remote target, protected merge target and multi-project isolation. |
| `docs/USAGE.md`, `docs/INSTALLATION.md`, `docs/ARCHITECTURE.md` | Add schema-v1 YAML override example and inheritance rule after tests pass. |

Config resolution pseudocode:

```python
effective = global_config.base
source = "global"
if "base_branch" in project_yaml:
    effective = validate_git_branch(project_yaml["base_branch"])
    source = "project"
return replace(global_config, base=effective, base_branch_source=source)
```

**Failure/recovery:** Reject invalid configured refs before any Git mutation. If the requested remote base is absent, report its name and remote; never switch to `main` silently. **Acceptance:** WM-04. **Verification:** focused config/branch tests plus both canonical suites.

## WM-03 — Safe local macro dispatch and final status

**Status:** Proposed. **Dependencies:** WM-02 plus SUB-003's verified selection/context and explicit already-satisfied application/branch semantics (FS-00R, FS-01/FS-02 as needed). **Non-goals:** PR creation, merge or automatic repair ZIP creation.

| Path | Ordered work |
| --- | --- |
| `apatch_lib/core/actions.py` | Retain the existing tuple and numeric identifiers exactly. Do not assign numbers to macros or alter `action_number()` behavior for old input. |
| `apatch.py` | Extend top-level `op=` parsing with a separate set `APPLY_PATCH`, `APPLY_PATCH_CHECK`, `MERGE`, `RUN_ALL`; route macros separately from exact `opSeq`. Reject combination with `opSeq` or `handoffSeq` until explicitly specified. Preserve the old read-only `STS`/`AUD` fast paths. |
| `apatch_lib/macros.py` (**new**) | Represent a plan as immutable goal, verified context, selected patch identity, step list and evidence. Implement local `APPLY_PATCH`/`APPLY_PATCH_CHECK` only in LOOSE. Recompute state after each step; use existing workflow dispatcher for each atomic action and its journal, but never replay a positively satisfied `APL`/`BRN`. Limit ambiguous contexts to a structured stop. |
| `apatch_lib/sequence.py`, `apatch_lib/workflow.py` | Reuse operation-event recording and result taxonomy without silently changing deterministic `opSeq` behavior. A genuine `NO_OP` cannot become success without fresh proof. |
| `apatch_lib/status.py`, `apatch_lib/console.py` | Supply best-effort final read-only `STS` on macro success/error/cancel, preserve original exception and exit status, display executed/already-satisfied/not-run steps and exact next action. ANSI styles are optional and removed for non-TTY/`NO_COLOR`. |
| `tests/test_sequences.py`, `tests/test_handoffs.py`, `tests/test_status.py`, `tests/test_operation_journal.py`, `tests/test_config_cli.py` | Test fresh base ZIP-first APL/BRN; repeated last-applied ZIP; pending BRN; current matching feature; disjoint/manual edits; wrong checkout; ambiguous history; corrupt cache; missing ZIP; repeated local command; final STS on failed CHK and failed STS; strict/force rejection; exact `opSeq` unchanged. |

Planner sketch:

```python
def execute_macro(name, selected_zip):
    original_error = None
    try:
        context = reconcile_local_session_and_archive(selected_zip)
        plan = derive_local_steps(name, context)
        for step in plan:
            context = reverify_context(step)
            if context.proves_already_satisfied(step):
                report_satisfied(step, context)
            elif context.is_safe_to_execute(step):
                run_existing_atomic_action(step)
            else:
                raise SafeBlock(context.recovery)
    except Exception as error:
        original_error = error
        raise
    finally:
        try:
            show_read_only_status_of_selected_workflow()
        except ExpectedStatusError as status_error:
            report_status_unavailable_without_masking(original_error, status_error)
```

**Failure/recovery:** A status read failure never makes a failed macro successful. No tool-driven reset, `git clean`, re-extraction of a verified applied ZIP, or implicit `followup=true`. **Acceptance:** WM-05–WM-07, WM-10–WM-11, WM-16. **Verification:** synthetic LOOSE workflows plus mode-compatibility tests.

## WM-04 — Explicit prepare commands and stable-check policy

**Status:** Proposed. **Dependencies:** WM-03 and existing `CheckWorktreeChanged` handling. **Non-goals:** executing arbitrary shell strings outside existing configured argv validation, hiding repeated source modifications, modifying direct `CHK` defaults.

| Path | Ordered work |
| --- | --- |
| `apatch_lib/model.py` | Extend per-project YAML with optional `prepare_checks` list of validated argv commands and `check_worktree_policy` enum `stop|recheck_once`. Use `stop` as default; reject booleans, integers, empty commands and unsupported keys. |
| `apatch_lib/gitutil.py` | Add a bounded per-path fingerprint inventory: path, status/index OID/mode, file bytes, execute bit and symlink identity. Preserve the old aggregate fingerprint function and avoid treating timestamp-only changes as drift. |
| `apatch_lib/loose.py` | Factor existing verification into one complete pass. Execute optional preparation before the first pass only when invoked through the macro policy. If every check passed but bytes changed, re-run the full list **once** when authorized. Require the last pass to leave an identical before/after snapshot; clear stale verification evidence whenever anything changes. |
| `apatch_lib/presentation/execution.py`, `apatch_lib/console.py` | Print changed path details, attempt number, stable/unstable outcome, preserved edits and recovery; do not attribute mutation to the runner without evidence. |
| `tests/test_sequences.py`, `tests/test_modes.py`, `tests/test_safety.py`, `tests/test_config_cli.py` | A formatter converges after first run; perpetual formatter changes; failed second run; manual concurrent edit; index-only mode drift; new untracked output; changed executable bit; symlink swap; repeated timeout; `skipApproves=true`; no writes to GitHub. |

Algorithm:

```python
run_optional_prepare_commands_once_if_enabled()
for attempt in range(1, 3 if policy == "recheck_once" else 2):
    before = capture_checked_paths_and_bytes()
    run_all_required_canonical_checks()
    after = capture_checked_paths_and_bytes()
    if before == after:
        persist_verified_final_fingerprint()
        return SUCCESS
    invalidate_old_check_evidence()
    report_exact_path_differences(before, after)
raise ChecksChangedWorktreeWithRecovery()
```

**Failure/recovery:** This stage never treats zero check exit codes as sufficient when checked bytes changed. Preserve all edits, forbid publication after unstable verification, and do not repeat non-idempotent operations. **Acceptance:** WM-06, WM-12–WM-14. **Verification:** focused stable/unstable synthetic formatting plus both canonical suites and macOS path testing when available.

## WM-05 — Guarded MERGE and RUN_ALL macros

**Status:** Proposed. **Dependencies:** WM-02–WM-04 and SUB-003's safe commit scope plus publication/PR revision reconciliation (FS-04–FS-06). **Non-goals:** relaxing GitHub review/CI, force-pushing, merging a guessed PR or retrying uncertain remote mutation.

| Path | Ordered work |
| --- | --- |
| `apatch_lib/macros.py` | Complete `MERGE` and `RUN_ALL` using explicit terminal goals. Reconcile revision evidence before CMT, PSH, PR, MRG and SYN; handle exact proven already-satisfied steps without rewriting history. A new ZIP on a clean base starts a new feature session regardless of an older merged branch name. |
| `apatch_lib/context.py`, `apatch_lib/session.py` (from SUB-003 if implemented) | Reuse persistent session ID, exact commit scope, current verified HEAD/branch/remote, patch ordering, PR revision and merge/sync evidence; never derive authority from the tool-global activity ledger. |
| `apatch_lib/github.py`, `apatch_lib/loose.py`, `apatch_lib/force.py` | Delegate only to existing guarded publication operations after independent prerequisite checks. Do not reissue remote writes with unknown outcomes. Ensure synchronized completion checks the configured base branch. |
| `apatch.py`, `apatch_lib/status.py`, `apatch_lib/console.py` | Publish final macro outcome and always attempt read-only `STS` without suppressing remote uncertainty or changed-check failure. Clearly warn when `skipApproves=true` allows GitHub mutation. |
| `tests/test_github.py`, `tests/test_branches.py`, `tests/test_sequences.py`, `tests/test_operation_journal.py`, `tests/test_status.py` | End-to-end synthetic Git lifecycle; reused commit/open PR/merged PR; PR source SHA changed; protected target; review/CI pending/failing; remote unreachable; mutation timeout; failed sync after merge; manual commit/push; dirty unrelated file; two successive feature sessions; failed final status. |
| `README.md`, `docs/USAGE.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md` | Publish copyable macro examples only after the corresponding implementation is verified; do not claim planned macros are available prematurely. |

Publication sketch:

```python
context = require_exact_feature_session_and_checked_commit_scope()
commit_if_missing_and_verified(context)
push_if_remote_fast_forward_and_not_yet_published(context)
pr = read_or_create_one_matching_pr_without_mutation_retry(context)
require_current_review_ci_and_pr_head(pr, context)
merge_once_and_confirm_exact_pr_revision(pr)
sync_configured_base_fast_forward_only()
require_current_local_base_matches_verified_remote()
report_final_status_without_masking_errors()
```

**Failure/recovery:** A published commit or PR is not rolled back. If a remote mutation becomes indeterminate, stop before any other remote write and provide the exact read-only reconciliation action. If MRG succeeded but SYN failed, a subsequent macro reconciles the merged PR before attempting only SYN. **Acceptance:** WM-08–WM-11, WM-15–WM-16. **Verification:** complete synthetic Git/GitHub mock matrix, all existing suites, and review of terminal/branch cross-platform behavior.

## WM-06 — Deferred visible retries and read-only GitHub reconciliation

**Status:** Future, non-urgent. **Dependencies:** WM-05 publication context and
existing revision-scoped GitHub PR identity; this stage can be implemented
separately after the context prerequisite is verified. **Non-goals:** retrying
`gh pr create`/`gh pr merge` blindly, weakening safety gates, introducing a
background worker, or silently converting ambiguous remote evidence to success.

| Path | Ordered work |
| --- | --- |
| `apatch_lib/model.py`, project YAML validator | Define validated bounded settings for maximum read attempts, total recovery budget and retry delay; preserve `github_timeout_seconds` per-call cap and existing default read retry count. Reject non-finite, negative, oversized and boolean numeric values; document precedence and old-config compatibility. |
| `apatch_lib/github.py` | Consolidate classified transient **read-only** retries under one wall-clock deadline. After indeterminate PR create/merge, query live evidence through a bounded, read-only path; adopt only an exact, unique repository/base/head/source-SHA match and, for merge, verified merge evidence. Never issue an additional mutation automatically. |
| `apatch_lib/gitutil.py`, `apatch_lib/console.py` | Supply bounded timeout/cancellation and flushed attempt/progress output, including start, attempt `i/n`, remaining budget, backoff and optional low-frequency heartbeat. Sanitize terminal output and redact PR body/credentials. Terminate timed-out child processes safely; never leave silent indefinite calls. |
| `apatch_lib/loose.py`, `apatch_lib/force.py`, `apatch_lib/status.py`, `apatch.py` | Reconcile remote results only through existing protected PR/revision checks. Preserve local state and `UNKNOWN_REMOTE_RESULT` if evidence remains ambiguous; give precise recovery commands and distinguish recorded from verified outcomes. |
| `tests/test_github.py`, `tests/test_sequences.py`, `tests/test_operation_journal.py` | Mock GraphQL 504 and 502/503, DNS/timeouts, transient success, permanent 401/403 and invalid requests; lost PR-create acknowledgement with matching PR, no PR, multiple PRs and incorrect SHA; uncertain merge with and without live proof; budget expiration, explicit cancellation, redirected `NO_COLOR` output and no second remote mutation. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md` | Document knobs and copyable recovery examples **after** implementation, without claiming speculative retries are installed. |

**Algorithm:** Reserve a monotonic wall-clock deadline for the entire transport
recovery operation, not just each subprocess. Before every read-only attempt,
calculate `min(remaining_budget, configured_per_call_timeout)`; print and flush
the operation/attempt/budget. Retry only classified transient transport errors
and only while both attempt and time caps permit. Use a small capped backoff.
After an uncertain mutation, prefer an exact verified PR/merge identity lookup
with that same bounded mechanism; if evidence is missing, stale, inaccessible
or contradictory, stop with the original indeterminate outcome. Never treat
"not observed" during an outage as evidence that nothing happened.

**Failure/recovery:** Exhausted retries are finite and observable. The original
unknown mutation result stays recoverable; no extra `gh pr create`, `gh pr merge`,
Git push or local sync is attempted without independent confirmed evidence.
The user receives a read-only inspection recommendation and a safe later resume
point. **Acceptance:** WM-17–WM-21. **Verification:** mocked `gh` integration
matrix, fake-clock deadline tests, safe interrupted subprocess handling, the
complete canonical suites and terminal behavior review on target platforms.

## 2. Gate before every release

1. Record the actual implementation base and changed paths; do not layer changes over an unverified branch or assume installed GitHub state.
2. Run focused tests for the modified contract, `sh ./run_tests.sh`, and `sh ./run_rare_checks.sh`, comparing results with the established baseline. No tests may use the developer's real Git/GitHub remote.
3. Verify CLI alias compatibility, status/progress immutability, terminal and redirected output, and behavior when activity/history is missing or malicious.
4. Verify the one-ZIP handoff has only modified source/docs/tests plus embedded `.apatch/params.json`, correct repository and new feature-branch metadata, and externally computed final digest.
5. Mark a stage implemented only after review of the resulting code and passing acceptance evidence. Keep later CLI options documented as **proposed** until shipped.
