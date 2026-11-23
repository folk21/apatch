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

| Specification | Task plans | Current focus |
| --- | --- | --- |
| [SUB-006 — Review Evidence Pipeline](active/review-evidence/subspec.md) | [Seven linked task plans](active/review-evidence/subspec.md#3-features-and-task-execution-boundaries) | [RE-05 — Retention, Export and Recovery](active/review-evidence/subspec.md#re-05), `READY_FOR_REVIEW`; no acceptance |

An active workstream has a single normative `subspec.md` containing all
features, tasks and acceptance oracles, and one `task_impl_plan_<nn>_*.md` per
task. See the [SUB-006 task index](active/review-evidence/subspec.md#3-features-and-task-execution-boundaries).
The final two tasks remain `RE-06 / UPD_DOCS` and `RE-07 / GEN_TESTS`.
Feature catalog and ownership: [FEATURES](../FEATURES.md) and
[feature cross-reference](feature-cross-ref.yaml).

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

Developer acceptance recorded on **2026-10-28**:

| Completed specification | Archived advisory plan | Accepted scope |
| --- | --- | --- |
| [SUB-001 — Workflow Control](archive/subspecs/subspec-01-workflow-control.md) | [P0 plan](archive/subspecs/subspec-01-workflow-control-implementation-plan.md) | P0.1–P0.5b |
| [SUB-002 — Execution History and Audit](archive/subspecs/subspec-02-state-history-audit.md) | [P1.1–P1.2 plan](archive/subspecs/subspec-02-state-history-audit-implementation-plan.md) | P1.1–P1.2 |
| [SUB-005 — Architectural Simplification](archive/subspecs/subspec-05-architectural-simplification.md) | [PLAN-005](archive/subspecs/subspec-05-architectural-simplification-implementation-plan.md) | AS-01–AS-07 |

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

The selected workstream is SUB-006 / RE-05 at `READY_FOR_REVIEW`; RE-06 and RE-07 are future draft tasks, not completed;
its selected task is `active/review-evidence/subspec.md#re-05`.
SUB-003 and SUB-004 are unselected drafts under `planned/`, not accepted.
The checkpoint may advance at a developer-directed stage boundary.
Product behavior is documented in [Usage](../USAGE.md) and
[Architecture](../ARCHITECTURE.md).