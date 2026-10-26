# APATCH-SPEC-001 — Patch Workflow and Quality Orchestrator

**Status:** DRAFT (GENSPEC); implementation is not authorized by this document.

**Owner:** `apatch` CLI and target-repository `.apatch/` integration.

**Sub-specifications:** [SUB-001 — Workflow Control](subspecs/subspec-01-workflow-control.md), [SUB-002 — Execution History and Reconciliation](subspecs/subspec-02-state-history-audit.md), [SUB-003 — Feature Sessions](subspecs/subspec-03-feature-session-planning.md), [SUB-004 — Operational Workflows](subspecs/subspec-04-operational-workflows.md), and [SUB-005 — Architectural Simplification](subspecs/subspec-05-architectural-simplification.md). **Plans:** [PLAN-001](../plans/apatch-orchestrator-implementation-plan.md), [PLAN-003](../plans/feature-session-context-aware-implementation-plan.md), [PLAN-004](../plans/operational-workflows-implementation-plan.md), [PLAN-005](../plans/architectural-simplification-implementation-plan.md).

## 1. Purpose

`apatch` SHALL coordinate intake, validation, application, verification, and publication of LLM-generated patch handoffs while keeping the developer in control of local Git state and external side effects. It SHALL evolve into a configurable orchestrator of project quality checks, independent AI reviews, repository health, and spec-stage progress. It is not a replacement for Git, GitHub, or their safety policies.

## 2. Compatibility and safety baseline

- Preserve `LOOSE` (default), `STRICT`, and `FORCE` (recovery, not force-push).
- Preserve action IDs `0..11`: `EXT, BRN, BAP, APL, CHK, CMT, PSH, PR, MRG, SYN, STS, AUD`; `op`, `opSeq`, `handoffSeq`, `skipApproves`, and legacy handoff JSON schema v1.
- New patch handoffs use one explicit self-contained ZIP with embedded schema-v1 `.apatch/params.json`; a verified cached selection permits later operations without repeating the ZIP argument. Legacy explicit JSON paths remain supported. The read-only tool-wide `info=PROGRESS` query does not select a patch or target repository.
- Preserve LOOSE manual edits, multiple patches per commit, and deferred push.
- Keep existing state, history, migration, and logging data readable; never invent a verified commit, review, or merge.
- Keep safe ZIP extraction, worktree-preserving backups, Git guards, and non-force pushes.
- Keep GitHub review/check requirements distinct from interactive user approvals and remote branch protections.
- Before creating a new feature branch, reject any other unfinished local or remote feature branch; this mandatory gate cannot be disabled by a mode or confirmation option.

Current behavior is documented in [Usage](../../USAGE.md) and [Architecture](../../ARCHITECTURE.md). These DRAFT requirements are not assertions about the current implementation.

## 3. Capability roadmap

| Capability | Requirement | Priority |
| --- | --- | --- |
| Current patch status | Provide read-only `10 [STS]` with branch, patch, commit, push, PR, and next-action evidence | P0 — SUB-001 |
| Next operation | Show the suggested next action number/code after each action | P0 — SUB-001 |
| Local PR review policy | Accept an explicit per-project override for zero-approval merges | P0 — SUB-001 |
| Local GitHub CI policy | Independently configure whether published GitHub CI checks are mandatory for merging | P0 — SUB-001 |
| Explicit handoff identity | Give every ZIP a same-stem JSON and require a named handoff on every invocation | P0 — SUB-001 |
| Single active feature branch | Require evidence that prior local and remote feature work has been merged before creating another branch | P0 — SUB-001 |
| Reliable GitHub reads | Retry transient read-only network failures once, avoid duplicate repository-identity queries inside one operation, and never auto-retry remote mutations | P0 — SUB-001 |
| Generated patch order | Detect skipped patches using `created_patches.txt` | P0 — SUB-001 |
| Command sequences | Run `opSeq` with detailed progress and error recovery | P0 — SUB-001 |
| Multi-project progress overview | Record tool-wide and per-project summaries under `<apatch_installation>/.apatch/progress/`; query recent global and per-project activity using `info=PROGRESS` | P0 — SUB-001 |
| Operation execution history | Persist numbered/coded attempts and outcomes in `.apatch/apply_patch.state.json` | P1 — SUB-002 |
| Global patch reconciliation | Audit missing/incomplete historical patch workflows and suggest recovery | P1 — SUB-002 |
| Operational macros, activity overview and stable checks | Add guarded `RUN_ALL`, `APPLY_PATCH`, `APPLY_PATCH_CHECK`, `MERGE`, a cross-project activity preface to `AUD`, project-local base branch selection and opt-in bounded check recovery | P1 — SUB-004 |
| Architectural simplification | Introduce explicit operation results, typed external boundaries, cohesive policy/CLI/audit modules, forward recovery and incremental non-mutating style checks without changing existing guards | P1 — SUB-005 |
| Git-native patch handoffs | Accept Git-format `.patch`/`.diff` files alongside ZIP archives through a safe, format-aware apply pipeline | Future P1 — dedicated sub-spec |
| Check adapters | Run tests, lint, static analysis, and security tools with typed results | P1 |
| Check scheduling | Trigger checks by action, patch count/size, elapsed interval, or spec milestone | P1 |
| Repository health | Track fresh evidence and distinguish healthy, degraded, blocked, unknown | P2 |
| Spec-stage progress | Follow explicit SDD stage IDs and run comprehensive final checks | P2 |
| Independent model review | Invoke Codex/API reviewers with budget and policy limits | P3 |
| Extension contracts | Add new check adapters without changing core Git orchestration | P3 |

The P0 behavior, including lightweight cross-project progress summaries, is owned by [APATCH-SUB-001](subspecs/subspec-01-workflow-control.md). The richer per-target execution evidence journal and historical reconciliation audit are owned by [APATCH-SUB-002](subspecs/subspec-02-state-history-audit.md); they SHALL correlate with P0 progress events instead of creating conflicting independent histories. Other future capabilities require subordinate specs before implementation.

### Git-format patch support (future scope)

`apatch` SHOULD support LLM-generated Git-native patches as an alternative to ZIP overlays, while preserving the existing explicit verification, commit, push, PR, and merge steps. The future format-specific sub-spec MUST distinguish plain Git diffs (`git diff` / `git apply`) from mailbox patches (`git format-patch`), define accepted extensions and handoff metadata, and specify path/mode/binary/rename/deletion validation, applicability checks, conflicts, rollback or forward recovery, and integrity verification. Ingesting a patch MUST NOT create a Git commit implicitly. Patch-order tracking and applied-patch history MUST eventually work across both ZIP and Git-patch handoffs without invalidating legacy ZIP records. Git-format input support is a roadmap item, **not** current functionality or part of P0.

## 4. Planned quality-check policy

Each future check SHALL have a unique ID, adapter or argv command, timeout, required/advisory classification, output/evidence contract, and scheduling policy. Supported scheduling classes SHALL include:

- **Frequent:** formatters, linters, static analysis, targeted/unit tests before configured `CHK`/`CMT` gates.
- **Periodic:** broader integration tests, model review, and security checks after configurable patch counts or accumulated changed-file/byte thresholds.
- **Milestone:** E2E, UI, stress/load, and full independent reviews at specific SDD stages, especially the final stage.
- **Manual:** run a selected check without waiting for its normal trigger.

Missing or unexecuted checks MUST be `NOT_RUN`/`UNKNOWN`, never implicit PASS. A required failed check MUST block its configured downstream action. Advisory results MAY warn without blocking. Skipped checks MUST show the reason. Existing canonical checks retain their current behavior until an approved adapter-stage migration.

## 5. Repository health (future scope)

Health SHALL be evidence-based and tied to the repository identity, branch, HEAD SHA, relevant worktree fingerprint, timestamp, and check configuration revision. Proposed aggregate states:

- `UNKNOWN`: insufficient or stale evidence.
- `HEALTHY`: all currently required evidence is fresh and successful.
- `DEGRADED`: advisory failures or overdue scheduled checks.
- `BLOCKED`: failed required checks or a violated repository safety invariant.

A changed revision SHALL invalidate earlier revision-specific health. Health is descriptive, not permission to merge or bypass GitHub policy. The console MUST show concrete reasons, not just a color/score.

## 6. SDD integration (future scope)

Spec-stage metadata SHALL reference actual spec and stage IDs, explicit acceptance criteria, and required verification evidence. A commit, push, or PR is never sufficient proof that an SDD stage is complete. A completed final stage MAY trigger an expanded, project-configured validation bundle.

## 7. Cross-cutting invariants

1. Reconcile actual external state before retrying non-idempotent operations. Unknown remote outcomes remain UNKNOWN until confirmed.
2. Lock and atomically replace project-local mutable metadata and the future tool-wide progress ledger; never erase unknown history or user changes. Maintain a clear master/derived distinction for multi-file progress views.
3. `skipApproves=true` bypasses prompts only. Archive integrity, Git safety, CI requirements, and server-enforced protections remain in force.
4. Do not initiate hidden network calls or costly model reviews; external checks require explicit policy, credentials, and budgets.
5. Console output SHALL show operation progress. Persist bounded/redacted error diagnostics, not complete test streams or secrets.
6. Patch-order metadata is not a content-integrity proof. ZIP checksums and Git identities remain independently validated.

## 8. P0 non-goals

Do not implement the future plugin framework, model reviews, scanner integrations, hosted/graphical repository dashboard, conditional scripting DSL, or automatic Git rollback as part of SUB-001. The read-only local CLI progress overview is explicitly in scope. No automatic commit/push/merge beyond explicitly requested operations.

## 9. Approval gate

This is a proposed first specification, not an accepted implementation baseline. Resolve the explicit open decisions in [SUB-001](subspecs/subspec-01-workflow-control.md#8-open-decisions) before marking it `ACCEPTED` and beginning P0 implementation.
