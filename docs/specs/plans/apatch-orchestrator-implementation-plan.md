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
| **P0.2b — Independent project CI policy** | Add project-local `require_required_checks` override; preserve the existing global default and unrelated merge gates. | AC-19/20/21; missing/pending CI, stale PR, remote/server rejection tests. |
| **P0.2c — Explicit unique handoff names** | Generate same-stem ZIP/JSON pairs, require a named handoff in `apatch.py`/`apatch.sh`, support stems under `downloads_dir` and explicit `.json` paths. | AC-22/23/24; parser, shell launcher, missing-name, status and multi-handoff tests. |
| **P0.2d — Single active feature branch gate (emergency)** | Introduce a shared preflight for STRICT/LOOSE/FORCE before new `git switch -c`, validating all previous feature branches against local/remote ancestry and GitHub PR evidence. | AC-25/26/27/28/29; temp bare-remote and mocked GitHub tests, plus `skipApproves=true`. |
| **P0.2e — Historical PR revision safety (emergency)** | Bind PR recovery, creation, merge, and synchronization to the current patch's pushed SHA; permit a new PR after an earlier PR for the same branch was merged at a different SHA. | AC-30–34; exact reproduction of a historical merged PR followed by an unmerged feature commit, and explicit checkpoint recovery tests. |
| **P0.2f — GitHub read resilience and invocation-scoped identity** | Retry transient read-only GitHub failures once, never replay uncertain create/merge commands, and reuse an already verified repository identity through one merge/reconciliation operation while rechecking local origin. | AC-35–38; bounded retry, mutation no-retry, identity drift, mode/merge integration tests. |
| **P0.3a — Registry validation and ordering** | New small `apatch_lib/created_patches.py` or another single owner; compare optional local registry to legacy-compatible `AppliedPatchHistory`. Guard `BAP`/`APL` in all modes *before* side effects. | AC-05/06/08, invalid lines/duplicates/symlinks, history migration tests. |
| **P0.3b — Registry metadata transport** | Extend archive inspection/application to recognize a reserved `.apatch/created_patches.txt` member, validate append-only prefix, and store atomically as non-Git metadata. | AC-07, repeated ZIP, failed extraction/retry, ignored-file handling, no worktree false positives. Activate new ChatGPT packaging directive only once this is stable. |
| **P0.4a — `opSeq` core and console outcome clarity** | `apatch.py`, `apatch.sh`, `apatch_lib/workflow.py`, `apatch_lib/status.py`: parse existing operation IDs, dispatch sequentially, refresh state between steps, and present accurate, prominent result and next-step labels for standalone and sequenced actions. | AC-09/11/12/13/14/46–48, `skipApproves` true/false, parser parity, timeouts, terminal-color and no-op/error reporting. |
| **P0.4b — Multiple handoffs** | Add explicit optional `handoffSeq` mapping for `BAP`/`APL`, retaining prior cycle state; verify preflight against duplicate or missing inputs. | AC-10/11, successive patches on one branch, combined commit/deferred push, STRICT rejection. |
| **P0.5a — Tool-wide progress event storage** | Append redacted structured events to `.apatch/progress/progress.json` under one interprocess lock; regenerate collision-safe per-project JSON views; handle partial updates and unavailable storage. | AC-39/42–45; concurrent local processes, crash recovery, storage permission and identity tests. |
| **P0.5b — Progress query and configurable summaries** | Add read-only `info=PROGRESS` without handoff or target repository, global `progress_global_limit=8` and `progress_project_limit=3`, and project/global console summaries. | AC-40/41/43; CLI parser, non-Git invocation, display limits and no-side-effects tests. |

Stages P0.3b, P0.4b and the final progress storage location depend on developer acceptance of [open decisions](../active/subspecs/subspec-01-workflow-control.md#8-open-decisions). The user-facing P0 features remain in the **first sub-spec** even when delivered over multiple safe increments.

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

### P0.2b — File-level implementation: independent project CI policy

**Prerequisites:** P0.2 review override implemented and verified, existing global `require_required_checks` parsing in `load_config`, and existing CI guard in `github.merge_pr`. **Non-goals:** installing CI, synthesizing missing GitHub status checks, bypassing server branch protection, altering canonical local `CHK` execution, or making review/CI settings dependent on one another.

| File | Exact planned change |
| --- | --- |
| `apatch_lib/model.py` — `Config`, `load_project_config` | Add `required_checks_source` with default `global`. Allow project key `require_required_checks`, require `type(value) is bool`, inherit `global_config.require_checks` when absent, and propagate the effective setting and origin in `dataclasses.replace`. |
| `apatch_lib/github.py` — `merge_pr` | Display review and CI settings with independent origins before GitHub calls. Keep CI rollup/nonempty/required-check assertions inside `if config.require_checks`, without moving or bypassing PR identity/head/base/mergeability guards. Propagate failed `gh pr merge` without persisting `merged`. |
| `tests/test_apatch.py` | Test global inheritance, project `true`/`false` overrides, invalid YAML types, no published checks under both policies, pending checks with CI required, unapproved PR with review required, head drift, remote ref drift, and mocked GitHub refusal after CI opt-out. Verify no merge command is run when a remaining guard fails and output identifies `project`/`global`. |
| `docs/USAGE.md` | Explain two independent policy keys and their sources, examples for repositories without CI, default fail-closed behavior, local `CHK` distinction, and server-side restrictions. |
| `docs/specs/active/subspecs/subspec-01-workflow-control.md` | Add normative P0-2b policy and acceptance scenarios AC-19/20/21. |

```python
def load_effective_ci_policy(project, global_config):
    if "require_required_checks" not in project:
        return global_config.require_checks, "global"
    value = project["require_required_checks"]
    if type(value) is not bool:
        raise Abort("Project require_required_checks must be a YAML boolean")
    return value, "project"

def merge_pr(config, ...):
    display_merge_policy("review", config.require_approval, config.review_approval_source)
    display_merge_policy("CI", config.require_checks, config.required_checks_source)
    assert_pr_identity_head_base_remote_and_mergeability()
    if config.require_approval:
        require_approved_review()
    if config.require_checks:
        require_nonempty_published_checks()
        require_successful_github_required_checks()
    request_standard_github_merge()
    verify_github_reports_merged_before_persisting_state()
```

**Failure/recovery:** Configuration type failure stops at startup without mutating the repository. When CI is required, missing/pending checks remain actionable errors. When CI is not required, GitHub branch protections may still reject the merge; retain the pre-merge checkpoint and allow a later explicit retry after correcting GitHub settings. No automatic retry for an indeterminate remote result. Acceptance evidence: SUB-001 AC-19/20/21, focused mocked merge tests, full `sh ./run_tests.sh`.

### P0.2c — File-level implementation: explicit, unique handoff selection

**Prerequisites:** existing `downloads_dir`, `load_handoff`, current argparse/launcher normalization, and `STS` selection logic. **Non-goals:** changing ZIP names or JSON schema, resolving handoff stems by querying GitHub, implicit “most recent” selection, and performing multi-handoff sequences before P0.4b.

| File | Exact planned change |
| --- | --- |
| `apatch.py` — CLI parser, `main` | Make handoff positional mandatory. Introduce `resolve_handoff_path(identifier, downloads_dir)`: append `.json` if absent; bare filename/stem resolves under configured downloads, while explicit path remains local/absolute. Reject blank/unsafe bare names; keep explicit `.json` paths working. Remove project-name-derived default. Require explicit JSON for read-only `STS` too, without altering its no-write behavior. |
| `apatch.sh` | Remove implicit `$HOME/Downloads/<project>_patch_params.json` injection. Preserve mode-first and mode-second argument normalization; forward the chosen stem/path verbatim and exit with a usage error when absent. |
| `tests/test_apatch.py` | Assert no handoff errors before `git` changes, basename versus explicit path resolution, extension handling, two different JSONs in one downloads directory, mode argument orders, numeric/mnemonic `op`, `STS` requiring JSON even with `--patch`, shell-launcher behavior, and no regression to explicit absolute paths. |
| `README.md`, `docs/USAGE.md`, `docs/INSTALLATION.md` | Replace examples relying on implicit defaults, show stem-first syntax, separate ZIP/JSON naming rule, and current `downloads_dir`. |
| ChatGPT short and extended project instructions (**external artifacts**) | Replace hardcoded `apatch_patch_params.json` naming directive with same-stem `.json` for each ZIP; require separate copyable JSON basename next to each link. Preserve the exact two-file handoff and registry rules. |
| `docs/specs/active/subspecs/subspec-01-workflow-control.md` | Define the explicit handoff contract, intentional `STS --patch` no-handoff incompatibility, and AC-22/23/24. |

```python
def resolve_handoff_path(raw, downloads_dir):
    if not raw or raw in (".", ".."):
        raise Abort("A handoff JSON name is required")
    path = expand_user(raw)
    if not path.name.endswith(".json"):
        path = replace_name(path, path.name + ".json")
    if is_bare_name(raw):
        validate_safe_basename(path.name)
        path = downloads_dir / path.name
    return path

def run(argv):
    args = argparse_require_positional_handoff(argv)
    config = load_global_config()
    handoff = load_handoff(resolve_handoff_path(args.handoff, config.downloads))
    run_selected_operation_without_implicit_fallback(handoff, args)

def create_chatgpt_handoff(zip_name):
    stem = strip_final_zip_extension(zip_name)
    json_name = stem + ".json"
    write_json_with_patch_file(json_name, zip_name)
    display_copyable_filename_and_link(json_name)
```

**Failures and migration:** Missing positional handoff fails in argparse before config or runtime mutation. Missing/malformed JSON fails before state locks or Git operations. Existing handoff contents, absolute/relative `.json` paths, persisted workflow entries, and ZIP history remain unchanged. The former implicit default and no-JSON `STS --patch` mode are removed intentionally; the docs and help must call out this behavior. Explicit path selection prevents accidental application of an older default JSON when multiple patches coexist. Acceptance evidence: SUB-001 AC-22/23/24, shell syntax (`sh -n apatch.sh`), command help, focused tests, and full suite.

### P0.2d — File-level implementation: single-active-feature-branch gate

**Prerequisites:** read the current mode-specific `prepare_branch`/`new_branch` implementations, base/remote configuration, Git helper subprocess semantics, and existing PR discovery contracts. **Non-goals:** deleting old branches, automatically merging PRs, disabling existing branch adoption, enforcing a new policy on `APL`, and substituting checkpoint history for Git evidence. This emergency stage is developer-authorized independently of the remaining draft P0 roadmap.

| File | Exact change |
| --- | --- |
| `apatch_lib/branch_guard.py` (**new**) | Own `assert_no_unfinished_feature_branches(root, config, target)`: inspect local and remote feature refs, match merged PRs where Git ancestry is unavailable, reject open GitHub feature PRs, and conservatively abort when required evidence cannot be obtained. |
| `apatch_lib/branch_patch.py` | Call preflight from both STRICT `BRN` and `BAP` just before creating the new feature ref, including after the final branch-availability check. |
| `apatch_lib/loose.py` | Call preflight on the new-ref path in LOOSE `BRN`/`BAP`, without affecting existing local/remote branch reuse. |
| `apatch_lib/force.py` | Apply the same non-bypassable preflight on FORCE's new-ref path; preserve manual branch tracking/reconciliation. |
| `tests/test_apatch.py` | Test remote-only unmerged and local unmerged refs in all three modes under `skipApproves=true`, positive already-merged refs, dirty current feature, GitHub open PR when remote head disappeared, and network-failure fail-closed handling. Assert target branch was not created on failures. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md` | Explain the unconfigurable preflight, different local/remote error messages, fail-closed API behavior, and responsibility of the shared guard. |
| `docs/specs/active/spec-apatch-orchestrator.md`, `docs/specs/active/subspecs/subspec-01-workflow-control.md` | Record the immediate feature-serialization invariant and AC-25–29. |

```python
def assert_no_unfinished_feature_branches(root, config, target):
    remote_base, remote_features = fetch_remote_feature_heads_or_abort(root, config)
    local_features = list_local_feature_heads(root)
    prs = list_github_prs_or_abort_if_github_remote(root, config)

    for pr in prs:
        if is_another_open_feature_pr(pr, target):
            abort("сначала смерджи fb: " + pr.head_branch)

    for branch, tip in remote_features.items():
        if branch != target and not proven_integrated(tip, remote_base, prs):
            abort("сначала смерджи fb: " + branch)

    for branch, tip in local_features.items():
        if branch != target and not reflected_remotely_or_merged(branch, tip, remote_features, prs):
            abort("Unfinished local feature branch " + branch)

    return VERIFIED_CLEAR

def prepare_new_branch(mode, target):
    if target_already_exists_locally_or_remotely():
        return resume_existing_branch_using_mode_rules()
    request_confirmation_if_required()
    assert_no_unfinished_feature_branches(root, config, target)
    git_switch_create(target)
    persist_branch_created_checkpoint()
```

**Failure and recovery:** A remote or GitHub lookup failure is a hard block, not an approval request. The user first merges/publishes unfinished feature work, or restores remote connectivity, then explicitly retries `BRN`/`BAP`. Retained merged feature refs do not need cleanup. Git command failure must not be converted into an unverified "safe" pass. Unit and temp-remote tests verify the guard in all modes; the entire existing suite remains part of the acceptance gate.

### P0.2e — File-level implementation: historical PR revision safety

**Trigger:** A feature branch previously supplied PR #5 at commit `old_sha`, that PR was merged, and a later patch was committed and pushed to the same feature branch at `new_sha`. The old implementation refuses `PR` with "existing PR is closed" but `MRG` recovers PR #5 as merged without comparing `old_sha` to `new_sha`, then records a false `synced` state after updating local `main`.

**Prerequisites:** Verify `force._recover_pr`, `force.merge`, `force.sync`, `github.pr_list`, `github.create_pr`, `github.merge_pr`, `github.confirmed_merged_pr`, and `github.sync_base` against the current snapshot. **Non-goals:** Git history rewrites, deleting/renaming existing feature refs, reverting commits, automatic remote PR creation without consent, changing CI or review policy, inventing a merge based on equivalent file contents alone, and modifying the user repository's checkpoint without an explicit recovery action.

| File | Exact change |
| --- | --- |
| `apatch_lib/github.py` | Add a shared `assert_pr_matches_revision` identity/commit guard. In `create_pr`, select only an open PR matching the pushed SHA; distinguish historical merged/closed PRs at older revisions, refuse duplicate PRs for the same revision, and verify that **exactly one** open PR exists after creation even when historical entries remain. On explicit PR replacement, update `pr_number`/`phase` and remove stale `local_base_head`. In `merge_pr`, select the single recorded **open** PR by number from the historical listing (not `len(all_prs) == 1`), reject competing open PRs, and verify the post-command PR still identifies the intended SHA. In `sync_base` require source SHA/base/PR number/`mergedAt` before Git synchronization. Extend the `pr_list` JSON fields with `mergedAt` and, in `confirmed_merged_pr`, disambiguate multiple historically merged PRs by recorded SHA and require a nonempty merge timestamp without adding another API round-trip. |
| `apatch_lib/force.py` | Add `_expected_pr_revision` using recorded pushed/committed SHA or a verifiable local feature ref for manual recovery. Change `_recover_pr` to consider `OPEN`/`MERGED` PRs only when their `headRefOid` equals that revision; refuse historical mismatches before checkpoint mutation. Preserve PR number binding unless a developer explicitly invokes `PR` to reconcile. Recheck recorded `synced` state on retry instead of asserting that its old evidence remains verified. |
| `tests/test_apatch.py` | Add local temporary-Git reproduction of a new commit following an older merged PR; assert no details/sync/phase changes on mismatch. Mock a historical merged PR followed by a new open PR and verify correct selection. Test fresh PR creation despite historical PRs, duplicate blocking at identical SHA, explicit rebind from stale `synced`, post-merge SHA drift, `confirmed_merged_pr` selection with multiple merged historical PRs, and refusal to affirm a stale `synced` checkpoint. Keep approval/CI opt-outs independent. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md` | Document PR-head identity, repeated branch PR lifecycle, warning/reconciliation of old false-positive `synced` checkpoints, and the fact that CI/review settings never bypass SHA checks. |
| `docs/specs/active/subspecs/subspec-01-workflow-control.md` | Record non-configurable current-revision invariant, recovery rules, and AC-30–34. |

```python
def create_or_reconcile_pr(current_sha, recorded_workflow):
    require_remote_feature_tip_matches(current_sha)
    prs = list_all_prs_for_feature_branch()
    open_prs = filter_state(prs, "OPEN")
    if len(open_prs) > 1 or any(pr.base != expected_base for pr in open_prs):
        abort("Resolve ambiguous or misbased open pull requests")
    if open_prs:
        require_exact_pr_identity(open_prs[0], current_sha)
        select_pr(open_prs[0])
    elif any(pr.head_sha == current_sha for pr in historical_prs(prs)):
        abort("This exact revision already belongs to a closed or merged PR")
    else:
        request_confirmation()
        create_pr_once()
        active_after_create = list_open_prs_for_feature_branch()
        created = require_unique_open_pr(active_after_create)
        require_exact_pr_identity(created, current_sha)
        select_pr(created)
    if recorded_workflow.previous_pr != selected_pr.number:
        clear_stale_local_base_sync_evidence()
    persist_phase_and_current_pr("pr_created", selected_pr.number)

def recover_and_merge_pr():
    current_sha = recorded_pushed_sha_or_verified_local_feature_head()
    prs = list_prs_for_configured_base()
    matching = [pr for pr in prs if pr.state in ("OPEN", "MERGED")
                and pr.head_sha == current_sha]
    if len(matching) != 1:
        abort("An old merged PR is not proof for this patch revision")
    pr = matching[0]
    if recorded_pr_number_conflicts(pr.number):
        abort("Use PR operation to reconcile the selected PR first")
    verify_identity_and_source_sha(pr, current_sha)
    if pr.state == "OPEN":
        require_only_recorded_open_pr_among_historical_prs()
        verify_live_remote_head_and_project_merge_policy()
        merge_and_verify_current_pr()
    else:
        verify_merged_at_and_details_source_sha()
        checkpoint_phase("merged")
    verify_current_merged_pr_before_syncing_local_base()

def retry_sync_for_previously_synced_checkpoint():
    fast_forward_local_base()
    try:
        find_unique_merged_pr_for_recorded_sha_and_pr_number()
    except UnknownOrMismatch as failure:
        warn("Previous synced checkpoint is not currently verified", failure)
        leave_checkpoint_untouched()
        return
    report_verified_sync()
```

**Safe recovery after the incident:** Confirm via Git history and file tree diff whether the published feature commit's changes reached the base. If not, retain the feature branch. An explicitly selected `PR` on that branch and handoff may create/find a new PR at the current SHA, replace an obsolete PR association (even if its earlier phase was erroneously `synced`), and clear stale sync evidence; merge remains a separate deliberate action. A mere retry of `MRG`/`SYN` must not rewrite the previous checkpoint as success. If GitHub refuses a new PR on the historical branch, stop and select an independently reviewed manual recovery path. Do not force-push, delete refs, roll back remote merges, or alter unrelated workflow records as part of this stage.

**Acceptance evidence:** SUB-001 AC-30–34, distinct local-Git SHA tests and mocked GitHub records, preserved default mode/STRICT/FORCE behavior, `sh ./run_tests.sh`, and an integrity-checked ZIP/JSON handoff from the exact verified source baseline. The old target-repository `synced` record cannot be trusted without explicit revision reconciliation.

### P0.2f — File-level implementation: GitHub read resilience and invocation-scoped repository identity

**Objective and trigger:** A LOOSE `MRG` first validated `folk21/osmapdigger`, then repeated `gh auth status` and `gh repo view` while entering `github.merge_pr`; the second `gh repo view` failed with a GraphQL TCP timeout before invoking `gh pr merge`. The subsequent manually merged PR was safely reconciled through `SYN`. Remove redundant authenticated identity lookups without introducing an unverified repository cache or automatic retry of an uncertain remote mutation.

**Prerequisites:** Read `github.repository`, `remote_repository`, `gh_run`, `gh_output`, `merge_pr`, `sync_base`, `force._recover_pr`, `force.merge`, `workflow.merge`, and the existing tests. Preserve the configured `github_timeout_seconds` for each subprocess. Scope the cache to one synchronous operation only. **Non-goals:** long-lived authorization caching, a shared GitHub API client, retrying `gh pr create` or `gh pr merge`, weakening required checks/approvals, extending timeouts globally, and changing PR state-machine transitions.

| File | Symbols and precise responsibility |
| --- | --- |
| `apatch_lib/github.py` | Introduce `_TRANSIENT_GITHUB_ERROR` and `_github_read` with at most two total attempts (one retry) for explicitly known read-only `gh` subcommands. Dispatch read-only `gh_run`/`gh_output` calls through the retry wrapper; keep `gh pr create`/`gh pr merge` single-attempt. Introduce `verified_repository(config, root, already_verified)` to reuse a known verified `owner/repository` without remote API calls while still comparing it with the current Git origin. Accept keyword-only `verified_repo` in `merge_pr` and `sync_base`; return the verified repo from a confirmed merge. |
| `apatch_lib/force.py` | Return the resolved repo alongside the selected handoff and PR from `_recover_pr`; pass the same repo to `github.merge_pr` and `github.sync_base` in `merge`. Avoid any changes to FORCE commit adoption, push behavior, or recorded PR revision rules. |
| `apatch_lib/workflow.py` | In the STRICT `merge` method, pass the repo confirmed by `github.merge_pr` into the immediate `sync_base` call. Separate `SYN` invocations continue to authenticate independently. |
| `tests/test_apatch.py` | Cover initial transient read failure then success, two failed reads, non-retriable authentication rejection, non-retried `gh pr create`/`gh pr merge`, reuse of repo identity without a second `gh repo view`, fail-closed changed Git remote, and successful merge + sync under the existing SHA/CI/review safeguards. Keep every previous test running. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md` | Explain per-attempt timeouts, one retry on recognized transient read failures, absence of mutating retries, repository identity reuse only within one operation, and explicit `SYN` after a manual merge. |
| `docs/specs/active/subspecs/subspec-01-workflow-control.md` | Normative section 3.5 and acceptance cases AC-35–38. |

**Implementation order and control flow:**

```python
READ_ONLY_OUTPUT_COMMANDS = {
    ("gh", "repo", "view"),
    ("gh", "pr", "list"),
    ("gh", "pr", "view"),
}
READ_ONLY_RUN_COMMANDS = {
    ("gh", "auth", "status"),
    ("gh", "pr", "checks"),
}

def read_github_with_one_retry(argv, capture_output):
    for attempt in (1, 2):
        try:
            return bounded_gh_subprocess(argv, timeout=github_timeout_seconds)
        except Abort as error:
            if attempt == 2 or not recognized_transient_network_error(error):
                raise
            display_redacted_retry_warning(argv[:3])
            wait_briefly_before_retry()

def execute_github_command(argv):
    if argv_prefix(argv) in READ_ONLY_RUN_COMMANDS | READ_ONLY_OUTPUT_COMMANDS:
        return read_github_with_one_retry(argv, capture_output=needs_stdout(argv))
    return bounded_gh_subprocess_once(argv)

def verified_repo(config, previous=None):
    if previous is None:
        return verify_local_origin_against_gh_auth_and_repo_view()
    if current_origin_repository(config) != previous:
        abort("Git remote changed after GitHub repository verification")
    return previous

def loose_or_force_merge():
    handoff, matching_pr, repo = recover_current_revision_and_repo()
    if matching_pr.state == "OPEN":
        merge_pr_with_live_SHA_policy_checks(verified_repo=repo)
    if checkpoint.phase == "merged":
        confirm_merge_details_and_sync_main(verified_repo=repo)

def strict_merge():
    repo = merge_pr_with_live_SHA_policy_checks()
    if checkpoint.phase == "merged":
        confirm_merge_details_and_sync_main(verified_repo=repo)
```

**Failure and recovery:** Never replay an uncertain GitHub mutation: on `gh pr create` timeout, run `PR` again to discover existing PRs; on `gh pr merge` timeout, query current PR state through the normal recovery flow or use `SYN` if the PR was manually merged. A read retry must not cause an apparently successful subprocess to skip content validation. A stale or changed local remote is a hard error even if a previously valid repo name was supplied. One read request can last up to twice the configured timeout plus a short retry delay; it always has a finite upper bound and visible console feedback.

**Acceptance evidence:** AC-35–38 plus all earlier PR safety scenarios and `sh ./run_tests.sh`. Use mocked `gh` commands and local temporary Git repositories only; no live GitHub merge or network manipulation is needed to test this stage.

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
| `apatch_lib/workflow.py` | Provide a single operation-dispatch method callable from interactive, `op=`, or sequence contexts; produce accurate per-step results and refresh state between actions. Replace `Finished without an error` with `SUCCESS` only after verified completion; render a terminal `ERROR` banner on known action failure and preserve distinct no-op/cancelled/uncertain results. |
| `apatch_lib/status.py` | Keep the existing evidence-based recommendation calculation; render the primary `Next suggested: <number> [<CODE>]` on its own visually prominent line with subordinate alternatives. Reuse the same renderer in `STS`, standalone actions, and sequences without recomputing a fake next step on failure. |
| `apatch_lib/console.py` (**new, only if shared formatting warrants it**) | Centralize small ANSI/color and result-line formatting helpers. Color green `SUCCESS`, red `ERROR`, and bold cyan the next-action label only for supported interactive terminals; respect `NO_COLOR`, `TERM=dumb`, and non-TTY streams. Do not introduce dependencies or put escape sequences in logs. If a new module would only wrap trivial formatting, keep helpers in existing owners. |
| `apatch.py` | Add mutually exclusive `opSeq` argument; reject malformed/empty/unknown/duplicate-sensitive sequence forms before side effects; pass `skipApproves` and mode unchanged. Ensure exception handling emits one accurate attempted-operation error result with action number/code, elapsed time, and recovery context; do not double-report an error from both workflow and top-level CLI. |
| `apatch.sh` | Normalize shell `opSeq=...` and proposed `handoffSeq=...`; preserve spaces/argument boundaries and existing CLI aliases across macOS/Linux shells. |
| `apatch_lib/model.py` | Validate optional handoff sequence input, exact mapping of `BAP`/`APL` to selected handoffs, and patch identity changes. |
| `apatch_lib/loose.py`, `apatch_lib/force.py` | Check that shared branch and manual-operation semantics remain unchanged when an action is sequence-driven; avoid alternative special-case state machines. |
| `tests/test_apatch.py` | Parser parity, op-order, no-interaction, non-TTY, intermediate Git failure, network timeout, sequence stop, and two ZIPs/one deferred commit cases. Assert `SUCCESS`/`ERROR` for proven outcomes; separate `CANCELLED`, `NO_OP`, and `UNKNOWN_REMOTE_RESULT`. Test green/red/bold-cyan ANSI with a simulated TTY, absence of ANSI for redirected output, `NO_COLOR` and `TERM=dumb`, and visibly distinct suggested versus scheduled next steps. |
| `docs/USAGE.md` | Show both acronym/number forms, handoff selection, colored/monochrome result examples, prominent next-action number/code, error summary, and explicit manual resume procedure. |

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

**Console outcome and emphasis contract (SUB-001 §2.1, AC-46–48):** Implement this as part of P0.4a for **both** existing standalone `op=`/menu execution and new `opSeq`; it is not a sequence-only presentation change. First inspect `Workflow.interactive`, `status.display_recommendation`, and the outer exception handler in `apatch.py`. Separate the operation's actual outcome from its formatter, so the following flow does not equate a lack of exceptions with success:

```python
def present_operation_result(action, observed, started_at, output_stream):
    outcome = classify_actual_outcome(observed)  # SUCCESS, ERROR, NO_OP, CANCELLED, UNKNOWN_REMOTE_RESULT.
    print_result_banner(action.number, action.code, outcome,
                        elapsed_since(started_at), color_if_tty(output_stream, outcome))
    if outcome == "SUCCESS":
        print_prominent_recommendation(recommend_from_verified_or_recorded_state())
    elif outcome in {"ERROR", "UNKNOWN_REMOTE_RESULT"}:
        print_diagnostics_and_safe_reconciliation_without_advancing_workflow(observed)
    else:
        print_noop_or_cancellation_guidance(observed)
    return outcome

def color_if_tty(stream, outcome):
    if not stream.isatty() or "NO_COLOR" in environ or environ.get("TERM") == "dumb":
        return None
    return semantic_style_for_outcome(outcome)
```

The actual implementation MUST reliably restore ANSI styles, keep redirected output/logs escape-free, and render the same plain-text labels when colors are unavailable. `==> Next suggested: 4 [CHK]` remains the primary standalone recommendation line and includes the numeric ID and acronym; a sequence's `Next scheduled` label refers only to remaining explicitly selected steps. A failed operation MUST retain its nonzero exit status even if the new formatter executes successfully. An uncertain remote outcome MUST NOT be styled or recorded as a proven success or failure. Update existing text-assertion fixtures to accommodate a clearer banner without weakening assertions on phase, HEAD, next-action identity, or failure details.

At every failure, print step `i/N`, number/code, selected patch, branch, phase, last completed action, observed versus uncertain effects, remaining actions, exit status, and safe reconciliation instructions. No automatic rollback, replay of an uncertain mutating command, or continued execution after cancellation; the bounded P0.2f retry for read-only GitHub lookups remains permitted. `skipApproves=true` may suppress confirmations but MUST NOT skip safety gates. P0.5 will add bounded cross-project action summaries; P1.1 will add richer per-target evidence records without changing sequence behavior.

**Acceptance checkpoint:** SUB-001 AC-09–14 and AC-46–48; test failed step 1 versus failed step N, missing/invalid handoff, duplicate `BAP,APL` without distinct handoffs, CI rejection, timed-out GitHub operations, and standalone/menu/sequence result rendering under TTY/non-TTY conditions.

### P0.5a — File-level implementation: persistent multi-project progress

**Objective:** Retain the meaningful results of every `apatch` operation across target repositories so the developer can reconstruct which projects were active, what happened, and what remains. This stage implements durable data capture without a new CLI query. **Dependencies:** P0.1 status/evidence semantics; P0.2f bounded GitHub handling; ideally the shared action dispatch from P0.4a so sequence events use the same collector. A standalone-operation implementation may precede `opSeq`, but the collector interface MUST allow `sequence_id` and `step_index` later.

**Prerequisites:** Inspect `apatch.py:main`, `apatch_lib/workflow.py:interactive/execute`, `apatch_lib/status.py`, `apatch_lib/state.py:locked_state/save`, `apatch_lib/logging_setup.py`, `apatch_lib/model.py:Config/load_config`, `.gitignore`, and launcher resolution. Confirm source-of-truth paths using `Path(__file__).resolve().parent`; do not confuse tool installation state with project-local checkpoint storage.

| File | Exact change and responsibility |
| --- | --- |
| `apatch_lib/progress.py` (**new**) | Own `ProgressEvent`, `ProgressProject`, `ProgressStore`, canonical root fingerprinting, safe per-project basename allocation, JSON schema/version validation, redaction, interprocess `fcntl` locking, atomic/fsynced writes, derived-file regeneration, and read-only master snapshots. Do not create a competing GitHub client or open every project repository while reading. |
| `apatch.py` | Capture one top-level operation-attempt context before dispatch and its final result after dispatch/exception. Flush progress **after releasing** the target's `locked_state` to avoid inconsistent lock-ordering. Surface storage errors as explicit warnings separate from actual Git/PR results. Preserve nonzero exit codes for failed operations; do not call progress logging for `info=PROGRESS` itself. |
| `apatch_lib/workflow.py` | Expose a compact immutable result summary (operation ID/code, start/end phase/branch, stable next suggestion, source SHA, PR number, outcome); use the same result producer for direct/menu/sequence actions. Avoid inferring `SUCCESS` from absence of an exception when the operation was cancelled or returned a no-op. Record sequence-step context when P0.4 exists. |
| `apatch_lib/status.py` | Reuse the existing `RECORDED`/`VERIFIED` semantics when projecting a next action. Do not make historical events appear as live GitHub checks. |
| `apatch_lib/model.py` | Optionally add a progress directory field to `Config` only after checking compatibility with current positional constructor tests; keep progress data tool-global and independent of project `config.yaml`. Validate eventual global storage-path overrides against symlinks/out-of-tree traversal. |
| `.gitignore` | Ignore only the tool's `.apatch/progress/` runtime data; do not add or commit private progress events. |
| `tests/test_apatch.py` | Test first creation, two distinct projects, same-name collisions, idempotent `event_id` replay, permissions and symlink attacks, concurrent multi-process appends, derived corruption/missing-file repairs, failed/cancelled/uncertain operations, launch outside installed repo, and redaction. Use only temporary tool/project directories and mocked external calls. |
| `docs/ARCHITECTURE.md`, `docs/USAGE.md` | Describe two-level storage, event authority, no historical backfill, example event semantics, crash recovery, permissions, and the difference between cross-project activity and actual authoritative checkpoints. |
| `docs/specs/active/subspecs/subspec-01-workflow-control.md` | Own the normative section 6 and AC-39/42–45. |

**JSON structure and stable identity (illustrative schema v1; finalize after source inspection):**

```json
{
  "schema_version": 1,
  "projects": {
    "root-identity-hash": {
      "name": "osmapdigger",
      "root": "/absolute/canonical/path/osmapdigger",
      "history_file": "osmapdigger_progress.json",
      "last_event_id": "event-uuid"
    }
  },
  "events": [
    {
      "event_id": "event-uuid",
      "project_id": "root-identity-hash",
      "started_at_utc": "2026-10-24T11:00:00Z",
      "finished_at_utc": "2026-10-24T11:00:04Z",
      "operation_code": "SYN",
      "operation_number": 9,
      "result": "SUCCESS",
      "phase_before": "pr_created",
      "phase_after": "synced",
      "patch_file": "selected-patch.zip",
      "pr_number": 6,
      "error_code": null
    }
  ]
}
```

**Sequential implementation and pseudocode:**

```python
def identify_project(actual_repo_root, registry):
    canonical = securely_resolve_actual_git_root(actual_repo_root)
    stable_id = hash_normalized_root(canonical)
    if stable_id in registry:
        require_same_canonical_root(registry[stable_id], canonical)
        return registry[stable_id]
    human_name = validate_safe_basename(canonical.name)
    preferred = f"{human_name}_progress.json"
    filename = preferred if not registered_elsewhere(preferred) else (
        f"{human_name}__{stable_id[:8]}_progress.json"
    )
    return ProjectIdentity(stable_id, canonical, filename)

def capture_action_attempt(context):
    event_id = cryptographically_random_event_id()
    started = monotonic_clock_and_utc_timestamp()
    try:
        result = execute_existing_action(context)
    except Cancelled as exc:
        event = build_event(event_id, started, "CANCELLED", short_redacted(exc))
        raise
    except RemoteOutcomeUnknown as exc:
        event = build_event(event_id, started, "UNKNOWN_REMOTE_RESULT", short_redacted(exc))
        raise
    except Exception as exc:
        event = build_event(event_id, started, "FAILED", short_redacted(exc))
        raise
    else:
        event = build_event(event_id, started, classify_noop_or_success(result))
    finally:
        release_project_checkpoint_lock_before_flushing_progress_event()
        try:
            progress_store.append_event_if_absent(event)
        except ProgressStoreError as error:
            report_progress_warning_without_replaying_or_undoing_action(error)

def append_event_if_absent(event):
    ensure_private_non_symlink_tool_progress_directory()
    with exclusive_lock("progress.json.lock", bounded_wait=True):
        master = load_and_validate_json_or_initialize_new_store()
        project = identify_project(event.project_root, master.projects)
        if event.event_id not in master.event_ids:
            master.events.append(validate_and_redact(event))
            master.projects[project.id] = update_last_activity(project, event)
            atomic_write_fsync("progress.json", master, permission=0o600)
        atomic_write_fsync(project.history_file,
                           derive_project_history(master, project.id), permission=0o600)
```

**Failure cases and decision points:** Never hold the tool-global progress lock while attempting Git, network, or canonical checks. Preserve a stable lock order; do not acquire the target's checkpoint lock while holding the progress lock. Stop on malformed master JSON or unsafe symlink paths without destroying the earlier version. If the master write succeeds but the project view fails, the master wins; recover the derived view on the next write. If the tool installation is read-only, emit one concise warning and complete/reject the primary Git operation according to its **own** evidence, not the secondary history write. No automatic filesystem-wide scan or fabricated pre-feature timeline. Decide whether the storage root needs an optional XDG/App Support override before accepting the default path permanently.

**Acceptance checkpoint:** SUB-001 AC-39/42–45, targeted concurrent subprocess tests (two writers, two projects), deliberate exception injected between the two atomic replacements, schema and privacy fixtures, standard `sh ./run_tests.sh`. Normal operations must remain usable if progress persistence fails.

### P0.5b — File-level implementation: `info=PROGRESS` and configurable overview

**Objective:** From the `apatch` installation or any directory, show the latest global actions and per-project recent activity without knowing a handoff stem. This stage is read-only and depends on P0.5a durable master history, not on any network connectivity.

| File | Exact change and responsibility |
| --- | --- |
| `apatch.py` | Recognize `info=PROGRESS` and `--info=PROGRESS` as a separate parser mode with no positional handoff. Reject simultaneous `op`/`opSeq`/action modes. Resolve the installed tool root from `__file__`, load global config, render the progress query, and return without `repository_root`, `load_project_config`, checkpoint migration, or GitHub operations. |
| `apatch.sh` | Pass through the new information argument without applying an implicit handoff; preserve macOS/Linux shell quoting and existing positional usage. No mandatory shell change if the current launcher is transparent. |
| `apatch_lib/model.py`, `apatch.conf` | Introduce `progress_global_limit = 8` and `progress_project_limit = 3` in the **global** configuration; validate positive bounded integers (suggest 1..100 global and 1..50 per project). These values control displayed rows, not data retention. No target-project YAML keys are required. |
| `apatch_lib/progress.py` | Expose a strict read-only snapshot loader, deterministic newest-first sorting, project directory summary, recent-event filtering, and console renderer. Mark stored facts `RECORDED`; highlight uncertain outcomes and unfinished work. Never invoke `git` or `gh` for another project while rendering the overview. |
| `tests/test_apatch.py` | CLI dispatch with no handoff/no target Git repo; project summary exact row limits; invalid config; missing/empty progress; tie-breaking events; failed and cancelled actions; tool root with spaces; no file bytes changed by `info=PROGRESS`; separate `--help` and existing `op=STS` compatibility. |
| `README.md`, `docs/USAGE.md`, `docs/ARCHITECTURE.md` | Minimal README pointer and detailed usage/architecture examples; explicitly explain partial history for projects not yet invoked since installation. |

```python
def parse_cli(argv):
    if argv_contains_info_progress(argv):
        reject_conflicts_with_handoff_op_sequence_and_modes()
        return ProgressQuery()
    return parse_existing_required_handoff_cli(argv)

def show_progress(global_config, tool_dir):
    summary = read_only_validated_snapshot(tool_dir / ".apatch/progress/progress.json")
    print("==> APATCH GLOBAL PROGRESS [RECORDED]")
    print_events(sort_newest(summary.events)[:global_config.progress_global_limit])
    for project in sort_projects_by_last_activity(summary.projects):
        print_project_location_branch_patch_last_status_and_next_step(project)
        print_events(last_events_for_project(summary, project.id)[
            :global_config.progress_project_limit])
        flag_incomplete_or_uncertain_work(project)
```

**Acceptance checkpoint:** SUB-001 AC-40/41/43 and all P0.5a persistence tests. Display of a previous `MERGED` or `synced` result is explicitly a **recorded** historical fact; it does not replace `STS`, `SYN`, or live Git/GitHub confirmation. Future optional filters `info=PROGRESS project=<id>`, `info=PROJECTS`, and `--json` can be separately specified after the initial overview is validated.

## P1 — Execution history, global audit, and scheduled quality checks

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
