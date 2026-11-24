---
type: Specification Index
title: apatch Specifications
description: Navigation for the umbrella specification, active workstream, drafts, and archives.
---
# apatch Specifications

This directory contains the specification-driven development (SDD) record for
`apatch`. Sub-specifications describe intended behavior; separate implementation
plans record incremental engineering work. Acceptance is a developer decision,
not an automatic consequence of code or tests.

For rules governing spec changes, plan ownership, acceptance, and archiving,
see [SDD agent instructions](AGENTS.md). For contributor workflow and testing, see [Architecture](../ARCHITECTURE.md#development-and-verification) and [repository agent instructions](../../AGENTS.md).

## Document metadata

Every repository Markdown document uses `type`, `title`, and `description` in its
Open Knowledge Format YAML header. An individual `task_impl_plan_<nn>_*.md`
additionally uses `area` and `runType`: its `type` is `GEN_CODE`, `UPD_DOCS`, or
`GEN_TESTS`; its `area` is `CODE`, `DOCS`, or `E2E_TESTS`; and `runType` is
`DEVELOP` or `ACCEPT`. The matching task ID, normative `rtype`, dependencies,
feature IDs, approvals, plan link and status live only in `subspec.md`. The
validator checks exact plan-to-task pairing, catalog feature IDs and the three
routing fields against that source; no header authorizes implementation.
Run `python3 tools/specs/validate_docs.py` to validate the contract.

## Umbrella specification

[APATCH-SPEC-001 — Patch Workflow and Quality Orchestrator](umbrella_spec_apatch.md)
owns the overall goals, roadmap, compatibility and security invariants. It is a
DRAFT, not implementation authorization, and has **no umbrella implementation
plan**. Each scoped sub-specification owns its own task implementation plans.

## Active work

No workstream is currently selected. `STATE.json` uses `IDLE` with an empty
workstream list until the developer explicitly selects the next scope.
Acceptance of SUB-006 does not automatically authorize SUB-003 or SUB-004.

## Planned, unselected drafts

| Specification | Advisory plan | Status |
| --- | --- | --- |
| [SUB-003 — Feature Sessions](planned/subspec-03-feature-session-planning.md) | [PLAN-003](planned/subspec-03-feature-session-planning-implementation-plan.md) | DRAFT / ON_HOLD; FS-06 previously selected for review; unaccepted |
| [SUB-004 — Operational Workflows](planned/subspec-04-operational-workflows.md) | [PLAN-004](planned/subspec-04-operational-workflows-implementation-plan.md) | DRAFT / ON_HOLD; WM-04 review; WM-05 proposed; unaccepted |

Planned means *not currently selected*, not *unimplemented*. The original
plans and recorded candidate implementation status are retained. Move a
workstream into `active/<scope>/` and select a task only by developer direction.
No `apatch` production deployment or Git/GitHub publication is implied by
this SDD reorganization.

## Accepted and archived work

Developer-accepted workstreams:

| Completed specification | Archived advisory plan | Accepted scope |
| --- | --- | --- |
| [SUB-001 — Workflow Control](archive/subspecs/subspec-01-workflow-control.md) | [P0 plan](archive/subspecs/subspec-01-workflow-control-implementation-plan.md) | P0.1–P0.5b |
| [SUB-002 — Execution History and Audit](archive/subspecs/subspec-02-state-history-audit.md) | [P1.1–P1.2 plan](archive/subspecs/subspec-02-state-history-audit-implementation-plan.md) | P1.1–P1.2 |
| [SUB-005 — Architectural Simplification](archive/subspecs/subspec-05-architectural-simplification.md) | [PLAN-005](archive/subspecs/subspec-05-architectural-simplification-implementation-plan.md) | AS-01–AS-07; accepted 2026-10-28 |
| [SUB-006 — Review Evidence Pipeline](archive/workstreams/review-evidence/subspec.md) | [RE-01–RE-07 plans](archive/workstreams/review-evidence/subspec.md#3-features-and-task-execution-boundaries) | RE-01–RE-07; accepted 2026-11-24; no Git publication claim |

The original shared PLAN-001 was split by completed sub-spec ownership. P1.3,
future Git-native format adapters, P2, and P3 remain proposals in the
[umbrella roadmap](umbrella_spec_apatch.md#3-capability-roadmap); they were
**not** accepted as part of SUB-001 or SUB-002.

## Processing checkpoint

[`STATE.json`](STATE.json) records the current selected stage and active
workstreams only. It is not runtime state and does not record acceptance.
Its structure is described in [`state.schema.json`](state.schema.json).

```bash
python3 tools/specs/validate_state.py
python3 tools/specs/validate_features.py
sh ./run_tests.sh
```

No workstream is selected (`mode: IDLE`). The latest accepted workstream is
SUB-006, archived with all seven task plans. SUB-003 and SUB-004 remain
unselected drafts. Future stage selection requires explicit developer direction.
The separate repository-wide review has not yet been accepted or published.
Product behavior is documented in [Usage](../USAGE.md) and
[Architecture](../ARCHITECTURE.md).