# apatch Specifications

This directory contains the specification-driven development (SDD) record for
`apatch`. Sub-specifications describe intended behavior; separate implementation
plans record incremental engineering work. Acceptance is a developer decision,
not an automatic consequence of code or tests.

For rules governing spec changes, plan ownership, acceptance, and archiving,
see [SDD agent instructions](AGENTS.md). For contributor workflow and testing,
see [Development](../DEVELOPMENT.md).

## Active work

| Specification | Advisory plan | Current focus |
| --- | --- | --- |
| [APATCH-SPEC-001 — Orchestrator](active/spec-apatch-orchestrator.md) | [Future umbrella stages](active/apatch-orchestrator-implementation-plan.md) | DRAFT; future proposals |
| [SUB-003 — Feature Sessions](active/subspecs/subspec-03-feature-session-planning.md) | [PLAN-003](active/subspec-03-feature-session-planning-implementation-plan.md) | FS-04 review; FS-05–FS-06 proposed |
| [SUB-004 — Operational Workflows](active/subspecs/subspec-04-operational-workflows.md) | [PLAN-004](active/subspec-04-operational-workflows-implementation-plan.md) | WM-01–WM-02 present; WM-03–WM-05 proposed |

Active sub-specifications live in `active/subspecs/`; **their active plans live
directly in `active/`**, with matching `subspec-XX-...-implementation-plan.md`
filenames. The umbrella and its remaining future-stage plan also live in
`active/`.

## Accepted and archived work

Developer acceptance recorded on **2026-10-28**:

| Completed specification | Archived advisory plan | Accepted scope |
| --- | --- | --- |
| [SUB-001 — Workflow Control](archive/subspecs/subspec-01-workflow-control.md) | [P0 plan](archive/subspecs/subspec-01-workflow-control-implementation-plan.md) | P0.1–P0.5b |
| [SUB-002 — Execution History and Audit](archive/subspecs/subspec-02-state-history-audit.md) | [P1.1–P1.2 plan](archive/subspecs/subspec-02-state-history-audit-implementation-plan.md) | P1.1–P1.2 |
| [SUB-005 — Architectural Simplification](archive/subspecs/subspec-05-architectural-simplification.md) | [PLAN-005](archive/subspecs/subspec-05-architectural-simplification-implementation-plan.md) | AS-01–AS-07 |

The original shared PLAN-001 was split by completed sub-spec ownership. P1.3,
future Git-native format adapters, P2, and P3 remain proposed in the active
umbrella plan; they were **not** accepted as part of SUB-001 or SUB-002.

## Processing checkpoint

[`STATE.json`](STATE.json) records the current selected stage and active
workstreams only. It is not runtime state and does not record acceptance.
Its structure is described in [`state.schema.json`](state.schema.json).

```bash
python3 tools/specs/validate_state.py
sh ./run_tests.sh
```

The current selected workstream is SUB-003 / FS-04 at `READY_FOR_REVIEW`;
SUB-004 remains `ON_HOLD`. The checkpoint may advance at a developer-directed
stage boundary. Product behavior is documented in [Usage](../USAGE.md) and
[Architecture](../ARCHITECTURE.md).
