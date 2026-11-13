# Modular redesign — proposed implementation plan

**Status: ADVISORY DRAFT (R1 design review only).**
**Design proposal:** [architecture.md](architecture.md).
**Contract set:** [README.md](README.md).
**Acceptance authority:** developer; no new active SDD stage is implied.

## 0. Preconditions and strategy

Use an **expand → migrate callers → contract** sequence within every wave.
Initially introduce an owning API and its typed models while leaving legacy
imports working. Then migrate *verified* production consumers in small
commits, add an architecture lint rule, and remove an alias only when every
consumer and compatibility test is accounted for. Never change persistence
fields or observed CLI behavior just to simplify the package layout.

At the start of each wave:

1. Capture current full Git HEAD, branch, status, tracked-file inventory,
   patch registry, test configuration and the exact accepted SDD checkpoint.
   Resolve the present nine untracked T1/T2 files before creating a new
   branch. Do not assume the R1 snapshot is a clean `main`.
2. Establish a current full checkout that includes `apatch`, `apatch.conf`
   and `.apatch/config.yaml`; their content was omitted in the snapshot.
   Read their policy before updating package imports or test harnesses.
3. Run `sh ./run_tests.sh`, `sh ./run_rare_checks.sh`, and
   `sh ./run_characterization.sh focused` as applicable on the unchanged
   baseline; record failures, source revision and OS/Python details.
   `sh ./run_characterization.sh full` is the final migration gate.
4. Independently verify active specifications, API consumers, tests and
   import graph. Resolve manual changes and user-accepted edits before ZIP
   application; do not run destructive Git cleanup in the developer checkout.
5. Use one tested incremental ZIP per independently verifiable slice, and
   require explicit consent for Git/GitHub mutations. An unsuccessful check
   never authorizes CMT/PSH/PR/MRG. Stages below can contain multiple small
   ZIP slices without changing their dependencies.

### Common negative/recovery matrix for every wave

- Test malformed inputs, unsafe paths/symlinks, corrupt or oversized external
  data, wrong repository/remote/HEAD, dirty worktree and unrecognized history.
- Inject interruption before/after the relevant filesystem write, lock,
  commit, push, PR or merge. Preserve user bytes and evidence; use verified
  forward recovery, not a blind `git reset --hard`.
- Verify no confirmation suppression bypasses guards, no automatic force push,
  and no remote mutation is repeated after an unknown outcome.
- Exercise Windows-sensitive path names only as synthetic validation inputs;
  real macOS/Linux subprocess and permission behavior needs separate runs.

## R1 — Design and traceability foundation (this review package)

**Scope:** source inventory, target ownership, dependency DAG, provisional
`contract.md` files, feature-to-symbol map and this linked plan. No runtime
modification, no SDD checkpoint change and no claim of developer approval.

**Produced files:** `docs/architecture/redesign/README.md`,
`architecture.md`, `implementation-plan.md`, `feature-ownership.md`, and
`contracts/{configuration,git,handoff,workflow,publication,review,audit,runtime}/contract.md`.

**Exit:** review proposed boundaries and open choices; confirm each verified
symbol has one future owner; validate document links and SDD checkpoint.
An explicit approved SDD sub-spec and plan is the prerequisite for R2.

## R2 — Core reduction, configuration and shared primitives

**Dependencies:** approved architecture contract, full baseline, T1/T2 gates.
**Objective:** remove I/O and feature policy from `core`/`model.py` before
moving Git, ZIP or remote code.

| Verified source | Per-file responsibility in the migration |
| --- | --- |
| `apatch_lib/model.py:Config`, `load_config`, `load_project_config`, `validate_base_branch`, `validate_runtime_filename`, `validate_log_subdirectory` | Create `configuration/models.py`, `loaders.py`, `validators.py`, `api.py`, `constants.py`. Preserve defaults, precedence, errors, tuple command shapes and source labels. Make old import names thin aliases after parity tests. |
| `apatch_lib/model.py:Abort`, `RemoteOutcomeUnknown`, `CheckWorktreeChanged` | Put neutral base error in `core/errors.py`; put remote uncertainty in `publication/errors.py`, check drift in `workflows/errors.py`. Retain compatible exception identity or documented subtype aliases during transition. |
| `apatch_lib/model.py:Handoff`, `parse_handoff_payload`, `load_handoff` | Stage pure Handoff DTO/regex/decoder into `handoff/models.py`, `constants.py`, `parsing.py`; keep original `model.py` entry points as adapters. Delay ZIP/filesystem effect migration until R3. |
| `apatch_lib/model.py:ReviewProvider`, `ScannerPolicy` | Move review-domain value objects to `review/models.py` with a validated configuration adapter. Keep historical constructor values unchanged. |
| `apatch_lib/core/contracts.py` and `core/enums.py` | Move GitHub PR types to `publication/models.py`; state records, `WorkflowPhase`, `OperationOutcome`, `ActionResult` to `workflows/models.py`. Keep old import compatibility and ensure no `core` import of `model.py`. |
| `apatch_lib/core/paths.py`, `storage/locking.py` | Keep reserved runtime identifiers owned by handoff/configuration and reviewed secure locking functions in the shared storage adapter; extract into `common/` only genuine multi-domain pure utilities. |
| `apatch_lib/application.py`, `cli_request.py`, `state.py`, `github.py`, `review_*.py`, tests | Migrate call sites in batches to configuration public API and domain DTOs; do not update all callers in one unreviewable diff. |

**Algorithm:** (a) add stable owner models/validators and backwards-compatible
wrappers; (b) run equivalence tests for each decoded value and exception; (c)
move loading/parsing functions; (d) retarget consumers by domain and run
focused tests; (e) enable AST prohibition of feature imports from `core`
and of I/O functions under migrated `models.py`.

**Independent tests:** `tests/test_config_cli.py`, `tests/test_validation.py`,
`tests/test_handoffs.py`, `tests/test_history.py`,
`tests/test_architecture_characterization.py`, plus new import/DTO
compatibility tests. Include invalid YAML, conflicting settings, missing
file, illegal branch, hash lengths and unknown compatible state fields.

**Exit:** MA-02/MA-03/MA-07, no new import cycles, unchanged CLI and source
fingerprints on synthetic targets, regular + full opt-in gates pass.

**Failure/recovery:** leave legacy imports intact; revert *only* the
isolated new ZIP in a disposable checkout when needed. For the user's target,
stop before CMT and use apatch state/status plus a reviewed corrective ZIP;
never discard manual changes.

### R2.3 completed value slice

`apatch_lib/workflows/` now owns the passive state declarations, phase/action
enums, operation identifiers, `ActionResult` normalization and verification
error class. Compatibility modules in `core` and `model` remain identity aliases.
Six internal consumer modules now import the owning public API. The name is
plural to avoid conflicting with the current `apatch_lib/workflow.py` engine.
The future R5 engine path is `workflows/engine.py`, not a new `workflow/`
package; changing the legacy entrypoint requires an independent gated slice.
The actual feature/session state store, action execution and persistence still
need extraction; value ownership alone does not satisfy all R2 architectural
exit criteria. Run regular, extended and characterization gates before
considering this slice accepted.

## R3 — Git adapter and handoff/producer boundaries

**Dependencies:** R2; verified new API contracts and source parity.
**Objective:** make ZIP and Git independent services, with publication using
a narrow Git port instead of cross-importing Git implementation details.

| Verified source | Exact migration direction |
| --- | --- |
| `apatch_lib/gitutil.py:run`, `output`, `repository_root`, `current_branch`, `head`, `worktree_inventory`, `worktree_fingerprint`, `remote_head` | Move to `git/subprocess.py`, `inspection.py`, `api.py`, `models.py`. Keep subprocess deadlines, streaming canonical output, secrets redaction and test monkeypatch seams. |
| `apatch_lib/gitutil.py:confirm`, `set_skip_approvals`, `confirmation_was_declined` | Move confirmation intent to `runtime/confirmation.py` injected into Git/workflow operations; preserve historical prompt outcomes and `skipApproves` safety semantics. |
| `apatch_lib/branch_guard.py`, `branch_reassignment.py` | Split Git ref queries and safe branch mutation into Git adapters; put ZIP-specific reassignment and workflow checkpoint validation in `workflow`. The central admission policy remains a single authority. |
| `apatch_lib/patch.py:inspect`, `apply`, `Archive`, and `handoff_selection.py` | Move archive entrypoint/validation to `handoff/inspection.py`, `extraction.py`, `api.py`, `models.py`. Preserve no-follow/safe paths, metadata, digest, created-patches and unknown history handling. |
| `apatch_lib/artifact_preflight.py:preflight`, `artifact_packaging.py:pack_source` | Move to `handoff/producer.py` and `handoff/api.py`; preserve source HEAD/worktree fingerprint, exclusive output, verified bytes and package path limits. |
| `apatch_lib/params_cache.py`, `created_patches.py`, `patch_history.py`, `zip_resume.py` | Move to handoff-owned cache/history/resume adapters; keep existing journal schema, lock placement, source/effective branch provenance and immutable ZIP identity. |
| `apatch_lib/branch_patch.py:BranchPatchActions` | Keep as temporary workflow compatibility adapter; stop it importing handoff internals after a validated handoff API is available. |

**Algorithm:** add `git.api` read-only inspection and guarded mutation
operations, then `handoff.api` verify/produce/apply operations parameterized
by stable Git reader/runner. Replace direct `gitutil` and `patch` imports in
consumers incrementally. Do not allow `handoff` to choose workflow phases,
`git` to parse GitHub PR responses, or either to change state checkpoints.

**Independent tests:** `tests/test_artifact_preflight.py`,
`tests/test_artifact_packaging.py`, `tests/test_handoffs.py`,
`tests/test_safety.py`, `tests/test_branches.py`,
`tests/test_branch_reassignment.py`, `tests/test_zip_resume.py`,
`tests/test_cache_recovery.py`, opt-in archive/recovery/destination tests.
Add negative fault injection for archive traversal, symlink parents, duplicate
members, history lock failure, commit/HEAD drift, and interrupted extraction.

**Exit:** MA-01/MA-04/MA-06/MA-08 for Git/handoff, producer output unchanged
except nondeterministic ZIP timestamps already allowed by existing contract;
recovery requires no new state migration.

**Failure/recovery:** if partial extraction is recorded, preserve original
checkpoint/backups and refuse unattended replay. Resume only when live bytes,
HEAD and archive identity match; never silently restore or delete files.

## R4 — Publication, review and audit ownership

**Dependencies:** R3 and verified Git/handoff API.
**Objective:** isolate external GitHub and review evidence, and make audit
consumers strictly read-only.

| Verified source | Exact migration direction |
| --- | --- |
| `apatch_lib/github.py:_validate_pr`, `decode_pr_list`, `pr_details`, `create_pr`, `merge_pr`, `sync_base` | Create `publication/models.py`, `constants.py`, `decode.py`, `transport.py`, `api.py`. Decode external camelCase keys once; use a semantic typed PR model inside the domain. Keep wire fields at ingress/egress, exact HEAD/PR revision checks, bounded read retry, no uncertain mutation replay. |
| `apatch_lib/code_review.py:run_review`, `require_fresh_review`, `review_matches` | Move to `review/api.py`, `providers.py`, `policy.py`, `models.py`. Inject checked-snapshot reader; keep the original review-required CMT gate and stop-on-uncertainty semantics. |
| `apatch_lib/review_artifacts.py`, `review_normalizer.py`, `review_context.py`, `review_evidence_api.py`, `review_retention.py` | Organize under `review/evidence/`, `review/normalization.py`, `context.py`, `retention.py` while exposing only the bounded `review.api` and read-only evidence port. Protect privacy and fail-closed quota admission. |
| `apatch_lib/audit_collectors.py`, `audit_rules.py`, `reconciliation.py`, `progress.py` | Move to `audit/collectors.py`, `rules.py`, `api.py`, `models.py`, `progress.py`. Only read validated snapshots; export progress events without owning workflow phase changes. |
| `apatch_lib/context.py`, `status.py` | Keep feature-session eligibility policy with workflow; move read-only audit-facing adapters to audit only where they do not make workflow depend on audit. |

**Algorithm:** first migrate GitHub decode/transport without changing
remote commands, next review evidence logic while preserving private storage,
then audit read-only collectors. Bridge old entry points with explicit
re-exports. Use immutable PR/snapshot models instead of passing mutable
`Workflow` across module boundaries.

**Independent tests:** `tests/test_github.py`, `test_publication_goals.py`,
`test_code_review.py`, `test_review_normalizer.py`, `test_review_context.py`,
`test_review_evidence_api.py`, `test_review_retention.py`, `test_audit.py`,
`test_audit_rules.py`, `test_progress.py`. Mock GitHub; test PR response size,
nullable status fields, pending/failed CI, moving PR HEAD, uncertain create,
symlinked/private evidence, quota rejection and export integrity.

**Exit:** MA-01/MA-04/MA-07/MA-08 for publication/review/audit. No workflow
state schema changes, no new model calls, unchanged external consent.

**Failure/recovery:** optional untrusted provider failure must block required
review and retain diagnostic evidence. Unknown GitHub mutation outcomes remain
indeterminate pending explicit live reconciliation; do not make speculative
retries or weaken required approvals.

## R5 — Workflow, runtime, static contracts and final cleanup

**Dependencies:** R2–R4 and their accepted checks.
**Objective:** complete isolation by having orchestration consume only public
APIs, with all models and load functions at their owners.

| Verified source | Exact migration direction |
| --- | --- |
| `apatch_lib/workflow.py:Workflow`, `loose.py:LooseActions`, `force.py:ForceActions` | Split `workflows/engine.py`, `modes/loose.py`, `modes/force.py`, `api.py`, `models.py`. Keep one state-machine owner; remove arbitrary cross-domain private calls via explicit ports. |
| `apatch_lib/planner.py:build_plan`, `execute_goal`, `sequence.py:OperationSequence`, `macros.py:execute_macro` | Move to `workflows/planning.py`, `sequencing.py`, `macros.py`; reuse one action execution/result path, not a second executor or bypass of phase checks. |
| `apatch_lib/state.py`, `operation_events.py`, `session.py`, `session_continuation.py`, `commit_scope.py` | Move to `workflows/state_store.py`, `journal.py`, `sessions.py`, `commit_scope.py`; maintain schema-v2 and v1 upgrade, atomic locks, exact original ZIP/commit provenance. |
| `apatch_lib/application.py:execute_request`, `cli_request.py:parse_request`, `help_reference.py`, `cli_inspection.py`, `presentation/execution.py` | Move to `runtime/api.py`, `cli.py`, `help.py`, `inspection.py`, `presentation.py`; retain historical `apatch.py` and shell commands without new flags. |
| `apatch_lib/core/actions.py`, `core/contracts.py`, `model.py`, `gitutil.py` | Finish migration of remaining domain symbols, trim compatibility modules only after full consumer inventory and deliberate public compatibility decision. |
| `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, `docs/USAGE.md`, `AGENTS.md`, module `contract.md` | Update implementation description and tests; keep `README.md` concise. Move each approved `docs/architecture/redesign/contracts/.../contract.md` into its implemented domain path with a single canonical copy. |

**Algorithm:** (a) isolate pure phase decisions and request/result DTOs;
(b) pass immutable snapshots/typed ports into mode handlers; (c) centralize
state/journal writes and transition validation, retaining existing locking;
(d) preserve action error categories and recovery points; (e) route CLI to
new facade, then collapse legacy adapters; (f) enforce import/model/API
contracts and the feature ownership map as a static gate.

**Independent tests:** full `tests/test_modes.py`, `test_sequences.py`,
`test_planner.py`, `test_feature_sessions.py`, `test_session_continuation.py`,
`test_guarded_commit.py`, `test_operation_journal.py`, `test_history.py`,
`test_status.py`, `test_macros.py`, `test_runner_scripts.py` and CLI
regressions. Compare exact operation outcomes, order, no-op evidence,
interrupted CMT/PSH/PR and approval behavior. Verify public `--help` strings
and prior Python imports against reviewed compatibility commitments.

**Final commands and evidence:**

```bash
python3 tools/specs/validate_state.py
sh ./run_tests.sh
sh ./run_rare_checks.sh
sh ./run_characterization.sh full
sh ./run_quality.sh all
```

`run_quality.sh` may be `NOT_RUN` when optional tools are unavailable; do not
claim success. Capture `sh -n` for altered launchers. Execute Linux and
macOS/Python matrix where available; real GitHub mutation tests remain mocked
unless a separate explicit integration authorization exists.

**Final exit:** every MA criterion proven on the approved exact source,
zero forbidden dependencies/cycles, verified canonical contracts and feature
mapping, no accidental business logic in `core`/`common` or I/O in models,
unchanged state migrations and security guards. Only then review whether the
old compatibility modules can be removed safely.

## Recovery and delivery policy across stages

- Preserve Git status, verified ZIP identity, journal/run IDs and test evidence
  before attempting any recovery. A ZIP generated for a stage never proves it
  was applied, checked, committed or merged.
- A failed incremental slice stops before Git publication; fix in a new
  independently reviewed overlay. Do not rewrite previous ZIPs, erase target
  state or force push.
- If current installed source differs from a snapshot or merges are pending,
  establish a new verified baseline before generating a dependent slice.
- Do not modify `docs/specs/STATE.json` merely because an architectural
  review document was created. The current selected workstream remains
  `review-evidence` / `RE-05` / `READY_FOR_REVIEW` until a developer-directed
  stage transition under `docs/specs/AGENTS.md`.

## R2 execution notes (non-normative progress)

- **R2.1 configuration/review models:** the configuration API, loaders,
  validators, Config DTO and review provider DTOs have been extracted with
  identity-preserving legacy imports. No workflow or persistence schema change.
- **R2.2 handoff/publication models:** Handoff DTO, metadata validation,
  legacy JSON I/O and protocol regex now have a `handoff.api` owner;
  GitHub PR wire-response TypedDicts and remote-uncertainty error now have
  a `publication.api` owner. Existing imports remain exact aliases; no
  ZIP application or GitHub operation has moved.
- **R2.3 pending:** remove remaining workflow-domain type ownership from
  `core.contracts` and relocate `CheckWorktreeChanged`. The existing
  `apatch_lib/workflow.py` module prevents a same-name `workflow/` package
  from being introduced without a dedicated import-compatibility migration.

These notes describe the source slices only. They do not change the active
SDD checkpoint, assert that an R2 stage has been accepted, or supersede the
normal verification and developer-review requirements above.
