# SDD Specification Index and Lifecycle

This directory owns specification-driven development (SDD) for `apatch`.
Normative sub-specifications define intended behavior; separate advisory
implementation plans define stages. A DRAFT document is not implementation
authorization. Only the developer accepts a finished sub-specification.

## Active specifications and advisory plans

| Specification | Implementation plan | Lifecycle |
| --- | --- | --- |
| [APATCH-SPEC-001 umbrella](active/spec-apatch-orchestrator.md) | [PLAN-001](plans/apatch-orchestrator-implementation-plan.md) | DRAFT |
| [SUB-001 — Workflow Control](active/subspecs/subspec-01-workflow-control.md) | [PLAN-001 P0](plans/apatch-orchestrator-implementation-plan.md#p0--first-priority) | DRAFT; implementation evidence exists |
| [SUB-002 — Execution History and Audit](active/subspecs/subspec-02-state-history-audit.md) | [PLAN-001 P1.1–P1.2](plans/apatch-orchestrator-implementation-plan.md#p1--execution-history-global-audit-and-scheduled-quality-checks) | DRAFT; implementation evidence exists |
| [SUB-003 — Feature Sessions](active/subspecs/subspec-03-feature-session-planning.md) | [PLAN-003](plans/feature-session-context-aware-implementation-plan.md) | DRAFT; partially implemented |
| [SUB-004 — Operational Workflows](active/subspecs/subspec-04-operational-workflows.md) | [PLAN-004](plans/operational-workflows-implementation-plan.md) | DRAFT; partially implemented |
| [SUB-005 — Architectural Simplification](active/subspecs/subspec-05-architectural-simplification.md) | [PLAN-005](plans/architectural-simplification-implementation-plan.md) | DRAFT; implementation review pending |

**Completed or archived specifications:** none formally accepted. Existing
implementation is documented in [Usage](../USAGE.md),
[Architecture](../ARCHITECTURE.md), and [Development](../DEVELOPMENT.md).

### Reconciled source checkpoint

Inspected clean baseline snapshot: `main` at
`efb94f794b06489c3d4898ffd42218f7b16e69fd`, generated
2026-10-27 11:25:35 UTC. Presence of code and tests is **not** evidence of
developer installation, formal review, acceptance, or macOS verification.

- **SUB-001 / SUB-002:** P0.1–P1.2 sources and tests exist (`STS`, `AUD`,
  cross-project progress and the operation journal). Legacy `BAP` retirement
  remains an unresolved compatibility decision.
- **SUB-003:** FS-00 linkage and FS-00R explicit ZIP resume have source/tests
  and current-facing usage documentation in the baseline. The separate FS-01
  candidate adds optional schema-v2 feature-session persistence, explicitly
  linked applied ZIP evidence, commit/PR association and regression tests.
  It is pending developer review and acceptance after installation; no CLI
  session planner is enabled. FS-02–FS-06 remain proposed.
- **SUB-004:** WM-01 read-only `AUD` activity and WM-02 project-local base
  selection have source/tests. WM-03–WM-05 remain planned; WM-06 is deferred.
- **SUB-005:** AS-01–AS-07 have corresponding source, regression and/or
  optional quality-tooling surfaces (`core/contracts.py`, `cli_request.py`,
  `action_applicability.py`, `audit_collectors.py`, `audit_rules.py`,
  `run_quality.sh`). They still need final evidence review before acceptance.

Reconcile this section against new Git provenance, actual tests and any
independent changes before advancing later stages. A successful increment
does not complete its whole sub-specification.

## Processing checkpoint

[`STATE.json`](STATE.json) is the only Git-tracked SDD **processing checkpoint**.
The structure is documented by [`state.schema.json`](state.schema.json);
validate it before staged work and in the canonical test suite:

```bash
python3 tools/specs/validate_state.py
sh ./run_tests.sh
```

`mode: SINGLE` permits one selected focus. Every workstream names its active
normative sub-specification, an existing plan stage ID, and its processing
phase. Allowed phases:

| Phase | Meaning |
| --- | --- |
| `DESIGN` | Reconcile prerequisites or design the stage. |
| `READY_FOR_IMPLEMENTATION` | Plan prepared; a separate developer task is still required. |
| `READY_FOR_REVIEW` | Submitted implementation awaits evidence-based review. |
| `AWAITING_DEVELOPER_DECISION` | Review findings were reported; the developer decides. |
| `BLOCKED` | An unresolved issue prevents progress. |
| `PAUSED` | Work is temporarily stopped. |
| `ON_HOLD` | Another workstream is selected. |

There is deliberately no `RUNNING`, `DONE`, or `ACCEPTED` phase. `STATE.json`
is neither a runtime monitor nor acceptance receipt. The selected workstream
is a navigation pointer, not a lock or execution authorization. Update it
**only at developer-directed checkpoints between stage executions**, not
during patch application, source-bound tests, or publication. Invalid/missing
state must be reported rather than inferred from README or other documents.

This file is completely separate from the product's target-local
`<target>/.apatch/apply_patch.state.json` used for ZIP/Git operation history.
The current proposed SDD checkpoint selects SUB-003 FS-01 at
`READY_FOR_REVIEW`; all other workstreams are `ON_HOLD`. The checkpoint
describes this handoff candidate, not a verified installation, independent
review or developer acceptance.

## Implementation-plan mapping and migration

Each **new staged sub-specification** must have a separate same-directory
advisory companion `<subspec-stem>-implementation-plan.md`, linked from its
normative owner. Include stable stage IDs, dependencies, exact verified code
ownership, per-file steps, illustrative algorithms, migration/failure/retry
semantics, positive/negative/recovery tests, exact commands and open decisions.
Label unverified paths or APIs as provisional. Normative requirements and
developer approvals always outrank an advisory plan.

The existing SUB-003/004/005 dedicated plans remain in `plans/` for now.
The shared legacy PLAN-001 contains explicitly separate **P0 (SUB-001)** and
**P1.1/P1.2 (SUB-002)** implementation sections; P1.3 is future adapter work.
Each mapped section belongs to its owner above;
neither needs a duplicate document solely to satisfy the new convention.
When either owner needs material plan changes or archival, split/relocate the
relevant existing sections into dedicated same-directory companions **without
copying hundreds of lines into parallel live plans**. Update all links and
ensure one authoritative copy of each stage. Do not archive the shared plan
until the other owner's content is safely migrated or no longer active.

## Developer-controlled lifecycle

1. **Inspect:** verify source SHA/worktree, current behavior, tests, owning
   sub-spec, plan, and validated `STATE.json` before any substantive stage.
2. **GENSPEC (explicit request):** create/update the normative sub-spec and
   advisory incremental implementation plan. Identify acceptance cases and
   unresolved decisions. A plan by itself never starts product implementation.
3. **Prepare:** select one small independently testable stage. Record its
   processing phase in `STATE.json` at a developer-controlled checkpoint.
4. **DEFAULT (explicit stage request):** implement, test, and hand off that
   stage; record exact commands, evidence, risks and remaining work. A ZIP,
   commit, or merged PR does not imply stage or sub-spec acceptance.
5. **Review:** inspect actual code and tests against normative acceptance
   criteria, the plan, stage changes and external evidence. An explicit REVIEW
   request is findings-only unless changes are also requested.
6. **Final review:** only after all stages, the developer requests a
   source-bound assessment of every acceptance criterion, tests, cross-stage
   regressions and known risks. Report an acceptance recommendation.
7. **Developer acceptance:** only an explicit developer decision accepts a
   sub-specification. No agent, passing test, Git operation, state phase or
   implementation-plan checkbox may grant acceptance automatically.
8. **Archive:** after explicit acceptance, synchronize current-state docs,
   umbrella references, this index and the checkpoint. **Move**, never copy,
   the accepted normative sub-spec and its implementation-plan companion to
   `archive/subspecs/` together, updating links. Archive the umbrella only
   when its separate acceptance target is complete.

Never auto-archive or silently promote specifications. Keep partially
implemented or unverified requirements active, regardless of code presence.
