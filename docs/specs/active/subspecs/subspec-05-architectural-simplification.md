# APATCH-SUB-005 — Architectural Simplification, Typed Boundaries, and Explicit Outcomes

**Status:** DRAFT (GENSPEC). AS-01 has a characterization-test implementation candidate. AS-02 has a separate typed-boundary implementation candidate; neither is presumed installed or accepted. Three AS-01 expected failures are resolved by AS-02, and the remaining status-advice failure belongs to AS-05.

**Parent:** [APATCH-SPEC-001](../spec-apatch-orchestrator.md). **Implementation plan:** [APATCH-PLAN-005](../../plans/architectural-simplification-implementation-plan.md).

**Design baseline:** the inspected `apatch` snapshot at `9f256d786d29d4121ea0116758af85a903d9636a` (2026-10-26 17:21 UTC), together with separately prepared WM-01/WM-02/FS-00 implementation candidates. Candidates are not evidence of installation. Revalidate affected functions against the actual repository HEAD before any DEFAULT-stage implementation.

## 1. Problem, objective, and scope

The current CLI is operational but concentrates too many decisions in a few functions. Parsing, handoff selection, safety guards, mode dispatch, result inference, persistence, GitHub interaction, and console rendering cross module boundaries. This makes a seemingly small change to ZIP continuation, `CHK`, or a PR operation capable of affecting unrelated flows.

The aim is **less decision complexity and fewer implicit contracts**, not an arbitrary increase in classes or a ban on `if` statements. Implement small, testable units, with explicit data at trust boundaries and one clear owner for each decision. Prefer pure functions for deterministic policy; reserve stateful classes for orchestration or resource ownership. A smaller function that merely delegates to a chain of opaque methods is not an improvement.

The refactor covers:

- CLI request normalization, validation, and dispatch; selection of a patch or an existing workflow.
- Application-layer execution coordination, action preconditions, and result classification.
- Mode-specific LOOSE/STRICT/FORCE policies and existing Git, archive, check, GitHub, and state adapters.
- Validation of persisted state and remote JSON, with small typed transfer objects where appropriate.
- Read-only repository audit and `STS` recommendations, console diagnostics, logging, and incremental static-quality tooling.
- Recovery evidence when an action has already affected Git, the worktree, a journal, or a remote system.

The detailed stage ownership is in PLAN-005; this document defines the normative target and testable invariants.

## 2. Existing evidence and hotspots

The audit of the cited snapshot counted approximately 5,600 production Python lines and 239 functions, with 213 functions missing at least one parameter or return annotation. These are directional baseline measurements, **not** acceptance thresholds or measurements of the developer's later installed version.

| Hotspot | Observed concern | Intended boundary |
| --- | --- | --- |
| `apatch.py:main()` | Roughly 251 lines combining CLI grammar, lifecycle validation, selection, preflight, locks and execution | Request parsing, read-only resolution, application dispatcher, small entry point |
| `apatch_lib/presentation/execution.py:OperationPresentation.interactive()` | Roughly 139 lines that execute actions, inspect Git snapshots, infer results, update progress and print messages | Application executor produces an explicit result; presenter only renders it |
| `apatch_lib/workflow.py:Workflow.options()` | Roughly 93 lines of mode/phase-dependent availability and dispatch-related conditions | Declarative action descriptors plus testable precondition functions |
| `apatch_lib/reconciliation.py:audit_repository()` | Roughly 208 lines mixing source collection, local/remote evidence, history correlation, findings and result construction | Evidence collectors, pure reconcilers, report builder; existing renderer stays separate |
| `apatch_lib/patch.py:inspect()`, `apatch_lib/model.py:load_project_config()` | Dense, partially untyped validation at external file boundaries | Validated archive/config objects with explicit error categories |
| `apatch_lib/loose.py`, `apatch_lib/force.py` | Mode policy, side effects and recovery intertwined | Explicit shared invariants and mode-specific choices; no broad behavioral unification |
| `apatch_lib/state.py:_upgrade_and_validate()` | Top-level `workflows` map validated but nested workflow records not consistently validated | Forward-compatible, complete record validation before consumers inspect fields |
| `apatch_lib/github.py:pr_list()` | Untrusted JSON list entries accessed without schema checks; malformed response can raise `TypeError` or `KeyError` | Typed, validated PR responses and a bounded domain error |
| `apatch_lib/status.py:recommend_next_action()` | New self-contained ZIP on base may be advised to run `BRN` before required `APL` | Evidence-based next-action policy consistent with executor guards |

## 3. Architectural boundaries and ownership

1. **Interface:** a CLI parser SHALL produce one validated `OperationRequest` (single action, exact sequence, advisory read-only query, or future macro). It SHALL not perform Git mutations while interpreting argument grammar. The `apatch.py` entry point SHOULD only perform bootstrap, invoke the application coordinator, render a result, and translate failures into existing exit codes.
2. **Application:** one execution coordinator SHALL own action sequencing, fresh precondition evaluation, outcome classification, checkpoint/progress correlation, and stop/continue decisions. The coordinator SHALL use existing operations and adapters; it SHALL NOT create an alternative lifecycle engine in parallel with `Workflow`.
3. **Domain/policy:** action identity, evidence classification, safe next-step recommendations and mode-dependent preconditions SHALL be independent of terminal output. The same policy inputs SHALL drive an `STS` suggestion and an action's live gate; `STS` is advisory and SHALL not itself authorize mutation.
4. **Infrastructure:** ZIP readers, Git commands, GitHub CLI, JSON/YAML/config and append-only journals SHALL validate external data at their boundaries and expose typed results or deliberate domain exceptions. Read-only inspection SHALL never create locks or repair data.
5. **Presentation:** human console output SHALL use a dedicated presenter/console API that controls stream, redaction, flush and optional color. `logging` SHALL record bounded diagnostic events; it SHALL NOT replace deliberate, readable CLI output. Unexpected failures SHALL not be hidden by generic `None` returns.
6. The design SHALL fit the existing `apatch_lib` layout. New modules are justified only when ownership genuinely becomes clearer; no mandatory `domain/services/repositories` directory hierarchy, dependency-injection container, metaclass registry, workflow DSL or blanket conversion of pure functions into classes.

The names `OperationRequest`, `WorkflowContext`, `ActionResult` and `WorkflowRecord` are proposed conceptual DTOs; the implementation plan MAY refine their concrete module location without altering these contracts. Immutable `dataclass` types are the default for internal records; `TypedDict` or a local validated mapping is appropriate for on-disk JSON. Introducing Pydantic v2 is **not required**: preserve the minimal runtime dependency footprint unless a separate measured justification exists.

## 4. Explicit operation-result contract

1. Every attempted atomic action SHALL return an explicit `ActionResult` or raise a classified exception translated at the application boundary. A `None` return SHALL not simultaneously mean declined confirmation, already satisfied, missing operation, or successful mutation. Git/worktree before/after snapshots MAY provide corroborating evidence but SHALL NOT be the sole source of outcome classification.
2. The result SHALL identify the requested action ID/code, `SUCCESS`, `ALREADY_SATISFIED`, `NO_OP`, `CANCELLED`, `BLOCKED`/`ERROR`, or `UNKNOWN_REMOTE_RESULT`, along with a concise reason, applicable verified facts, and safe continuation hint. `ALREADY_SATISFIED` requires fresh, positive proof, not merely an unchanged working tree. `NO_OP` is not success for sequencing without a separately proven contract.
3. Existing `OperationOutcome` and `RunOutcome` enums SHALL be reused or mapped deliberately; public progress and historical journal values SHALL remain readable. A future `BLOCKED` result may map to legacy `FAILED` where necessary, with a stable diagnostic reason, without rewriting old records. `STARTED` or indeterminate journal records SHALL not be fabricated as completed.
4. Confirmation decline SHALL be conveyed by a local explicit result or typed exception. The ambient confirmation flag in `gitutil.py` SHALL be removed **only after** its consumers are migrated and tests prove identical cancellation semantics. No global context variable SHALL become the authoritative outcome source.
5. The coordinator SHALL apply the same classification to single `op`, interactive menu, exact `opSeq`, and future macros. It SHALL preserve an exact sequence's user-provided order and stop rules, including the independently specified idempotent `APL`/`BRN` behavior of SUB-003.
6. `UNKNOWN_REMOTE_RESULT` SHALL remain a hard stop for subsequent mutations unless exact live, read-only reconciliation proves the side effect. No generic exception handler may turn uncertain PR creation/merge into a successful/no-op result.

## 5. Typed inputs and external schema validation

1. **Typing policy:** new and significantly edited functions SHALL annotate all parameters and return values, including `-> None`; public boundary contracts SHALL be fully typed first. Static typing SHALL be improved incrementally with a documented baseline. Avoid unbounded `Any` in core policy. `object`, `JsonValue`-style recursive values, and carefully isolated dynamic parsing types are acceptable at untrusted JSON boundaries until validated.
2. **Data objects:** repeated cross-module field bundles SHALL become `@dataclass(frozen=True)`/narrow enums or validated `TypedDict` where an on-disk mapping is intrinsic. Simple temporary lookup maps, sets, tuples and keyword dictionaries remain valid implementation details; a blanket ban on `dict`/`tuple` is not part of this requirement.
3. **State:** `state.py` SHALL validate each entry of `workflows` and each known field used by execution, including type, bounded identifier, optional SHA/phase/branch and required identity relationships. Invalid nested forms such as `"workflows": {"key": []}` MUST produce a controlled `Abort` before consumer access, without partial mutation or a surprise `AttributeError`.
4. **Compatibility:** schema-v1 and schema-v2 state, known legacy fields, previous operation runs, `superseded_by` history and forward-compatible unknown fields MUST remain readable. No read may destructively normalize unknown information. A migration SHALL preserve unknown compatible fields when rewriting, and shall only write during an already authorized locked mutation.
5. **GitHub:** JSON from `gh pr list`, `gh pr view`, optional audit remote snapshots and related commands SHALL be checked for shape, required fields, types, valid PR identity, optional nulls, response sizes and bounded text before consumers use it. Invalid replies MUST produce a useful controlled error and NEVER be interpreted as evidence of no existing PR or of a successful merge.
6. **Config and archive:** continue to validate the embedded schema-v1 handoff, safe ZIP members, downloaded-name/digest pairing, project YAML schema and path boundaries. Refactoring validators MUST preserve symlink, traversal, overwrite, size and changed-archive protections.
7. If data is valid but absent (no previous history, unknown PR or missing optional config), that state SHALL be distinct from a corrupted document or a failed transport request. Neither category permits an implicit fallback that weakens guards.

## 6. Preconditions, `STS`, mode behavior and ZIP continuation

1. Each atomic action SHALL have one authoritative set of **live** safety predicates: selected handoff identity, repository and configured base, active feature/session, branch/HEAD/remote ancestry, changed paths, check evidence, operation phase, and publication/review/CI policy where relevant. The presenter may show unavailable reasons, but cannot override predicates.
2. The policy SHALL distinguish *applicability* (can this action be started?) from *already satisfied* (is its exact intended effect independently proven?). A previous journal success is only evidence and must be checked against current Git, archive and, for publication, remote PR facts.
3. For a newly selected self-contained ZIP on a safe configured base, `STS` MUST recommend `APL` before `BRN`; after an initial ZIP-first `APL` on the base, pending `BRN` MUST be recommended. Legacy JSON and STRICT flows retain their actual existing valid order. Recommendations SHALL not list an action that deterministic CLI admission would reject in the same context.
4. The ZIP-resume, last-applied requirement and exact-sequence `ALREADY_SATISFIED` rules belong to [SUB-003](subspec-03-feature-session-planning.md), not this document. This refactor SHALL reuse their verified session resolver when implemented; until then it SHALL NOT pretend that unimplemented ZIP semantics are available.
5. Workflow macros, base overrides, stable-check reruns and deferred bounded GitHub retry belong to [SUB-004](subspec-04-operational-workflows.md). This refactor SHALL provide explicit result/evidence boundaries useful to those features but SHALL NOT quietly deliver them as part of a structural stage.
6. `LOOSE` manual edits and deferred commits, `STRICT` phase restrictions and `FORCE` recovery semantics SHALL remain independently represented. Shared checks may be factored only if regression tests prove identical mandatory guards. `FORCE` never means force-push or unreviewed overwrite; `skipApproves=true` continues to bypass confirmation prompts only.
7. Preserve IDs `0..11` (`EXT, BRN, BAP, APL, CHK, CMT, PSH, PR, MRG, SYN, STS, AUD`), `op`, `opSeq`, `handoffSeq`, `followup`, handoff ZIP/legacy JSON, configured base precedence, read-only `info=PROGRESS`, and published exit-code/diagnostic contracts. New macro names remain separate from numeric actions.

## 7. Audit and forward-recovery contracts

1. Refactor `audit_repository()` into bounded local evidence acquisition, registry/history correlation, workflow/run analysis, optional remote evidence acquisition, and pure finding/report assembly. `format_audit()` and cross-project `AUD` presentation remain separate. Audit SHALL be read-only and deterministic for the same snapshots.
2. Evidence SHALL distinguish `VERIFIED`, `RECORDED`, `UNKNOWN`, and `CONFLICT`; a previous phase string or tool-wide activity line SHALL not authorize a mutation. Existing finding codes and severity meanings MUST remain compatible unless an explicitly tested defect correction demands a documented difference.
3. Persisted state, applied-patch history, created registry, operation journal, global progress, Git refs and GitHub PRs are **not one atomic transaction**. The coordinator SHALL use forward recovery and explicit effect boundaries, never a claim of distributed atomicity.
4. After each confirmed effect, retain enough stable patch/branch/commit/PR identity to reconcile an interruption. After an unknown remote result, preserve the existing checkpoint and block replay of the mutation. Never run automatic `reset --hard`, clean, rebase, force push, remove user edits, or speculate that a failed journal write rolled back an already completed GitHub operation.
5. A failed audit, optional history read, lock acquisition, CLI presentation or progress recorder SHALL not be silently converted into evidence that the underlying operation succeeded. Diagnostic recording failures may warn without changing a previously proven operation outcome, as already contracted, but MUST remain visible.

## 8. Tooling, documentation and testability

1. Add Ruff lint and format-check in **non-mutating** mode, selecting a narrow initial rule set and baseline. Run `ruff format --check`, never `ruff format` as an implicit canonical verifier. Expand enforced scope in small patches; avoid one repository-wide reformat unrelated to the current stage. Preserve the existing source of truth for project-configured `CHK` and SUB-004's opt-in `prepare_checks` policy.
2. Add optional static type checking (mypy or Pyright) for touched/typed core modules, initially non-blocking if a measured baseline is still failing. The first rollout SHALL define Python version support, dependencies/tool availability and the exact enforced file set; do not silently change package installation requirements.
3. Write reproducible, isolated tests for policy functions, malformed JSON, cancellation, remote uncertainty, state migration, mode semantics, CLI aliases and interrupted persistence. Local Git integration tests SHALL use temporary repositories/bare remotes; GitHub tests SHALL use mocked commands.
4. Preserve the distinct regular and extended suites, manually triggered CI workflow unless separately authorized, cross-platform caveats, redaction, bounded output and the separation of `logging` diagnostics from user-visible console status.
5. Keep `docs/USAGE.md` descriptive of installed behavior and specs/plans descriptive of proposed behavior. The spec index SHALL list active drafts without stale hard-coded counts; no repeated architecture prose across README, AGENTS and DEVELOPMENT.
6. Refactor `tests/_support.py` only after production seams stabilize: reduce global `sys.path` manipulation and excessive shared imports without making fixtures harder to use or broadening test side effects.

## 9. Non-goals and safety constraints

- No big-bang rewrite, wholesale Python framework adoption, or required Pydantic runtime dependency.
- No absolute ban on `if`, `print`, `dict`, `tuple`, pure functions, or strictly isolated `Any` at JSON parsing boundaries. Complexity and contract clarity, not style slogans, are the measure of success.
- No behavioral rewrite of SUB-003 sessions or SUB-004 macros/CHK/retry during structural work; each keeps its own acceptance IDs.
- No implicit archive reapplication, hidden PR creation/merge, new automatic retry of remote writes, or relaxation of GitHub review/CI/Git integrity.
- No destructive migration of historical journals, user worktree changes, installed configuration, or non-owned `.apatch/` artifacts.
- No assumption that the attached snapshot reflects later locally merged candidates.

## 10. Acceptance criteria

| ID | Required observation |
| --- | --- |
| AR-01 | CLI, application policy, adapters and presentation have documented, test-enforced responsibilities; entry-point code no longer contains the per-action workflow decision matrix. |
| AR-02 | All newly introduced/meaningfully changed public functions and DTOs are typed; raw JSON is validated before reaching typed policy, without a mandatory new runtime dependency. |
| AR-03 | A declined prompt, genuine `NO_OP`, verified `ALREADY_SATISFIED`, successful mutation, safety block and unknown remote outcome are distinct in single, menu and sequence execution; outcome does not depend only on Git snapshot change. |
| AR-04 | Recorded operation runs, progress history and console summary agree on completed versus blocked/indeterminate outcomes; old journal data is readable and not rewritten during status inspection. |
| AR-05 | Nested malformed workflow records are rejected with controlled diagnostics before any user-source or Git mutation; compatible v1/v2 and unknown fields survive read and authorized write. |
| AR-06 | Wrongly shaped or malformed `gh pr list`/`gh pr view`/audit JSON raises a controlled error, does not create or merge a PR, and does not invent negative evidence. |
| AR-07 | `STS` on a new self-contained ZIP on base advises `APL` first, then `BRN` after ZIP-first application; advice and executor preconditions agree in tested LOOSE/STRICT/legacy contexts. |
| AR-08 | Existing action numbers, flags, local config precedence, 3 modes, return codes, single/sequence/menu output semantics and safety guards remain compatible, except separately documented bug fixes. |
| AR-09 | Audit is read-only across corrupt/missing optional history, no-remote and opt-in mocked remote modes; ordering, bounds, finding codes and report presentation remain equivalent for valid snapshots. |
| AR-10 | After interruptions at each state/history/Git/PR effect boundary, restart reconciles durable evidence and preserves developer changes; uncertain remote writes are never replayed without live proof. |
| AR-11 | Ruff format-check and lint plus a scoped type-check have explicit tool/config contracts, reproducible commands and no source-formatting side effects during checks. |
| AR-12 | Focused regressions, regular tests and extended tests are recorded for each implemented stage; platform gaps, unavailable tools and skipped checks are explicit, never reported as passed. |
| AR-13 | Each refactored hotspot has smaller cohesive responsibilities and fewer policy branches per function, supported by before/after complexity measurements and tests; no arbitrary LOC or class-count quota is imposed. |
| AR-14 | `docs/specs` index and development lifecycle links accurately distinguish installed source from proposed/candidate stages; no duplicate live-behavior documentation is introduced. |

## 11. Integration gates and open design decisions

The [implementation plan](../../plans/architectural-simplification-implementation-plan.md) sequences **AS-01 through AS-07** into independently reversible/tested increments. AS-01's test candidate recorded four known RED expectations without changing runtime behavior. The separate AS-02 candidate removes three `expectedFailure` markers after implementing and testing state and GitHub boundary validation; the fourth remains owned by AS-05. AS-03 explicit-result migration SHOULD precede broader WM-03–WM-05 macro orchestration; macro planning MUST not fork a second executor. Later stages may proceed incrementally alongside independent roadmap work after interface compatibility is verified.

Resolve before implementing the affected stage:

1. Exact initial result-model API and its mapping to `RunOutcome`/historical progress strings; especially `BLOCKED` versus legacy `FAILED`.
2. Field-by-field validation and pass-through policy for historical `WorkflowRecord` variants; confirm all legacy fixture shapes before making validation stricter.
3. Ownership of the source-of-truth operation preconditions between existing `Workflow.options()` and SUB-003's proposed session planner.
4. Ruff initial rule set, baseline-exception strategy, first type-checked modules and choice of type checker, without silently adding mandatory dependencies.
5. Which documentation describes the accepted implemented stages after their tests pass. Do not mark this DRAFT as completed merely because an implementation ZIP was generated.
