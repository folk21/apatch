# SDD Specification Index

This directory holds proposed normative specifications and implementation plans for `apatch`. Documents marked **DRAFT** are under discussion and do not authorize implementation.

## Status

| Category | Current status |
| --- | --- |
| Accepted normative specifications | None yet |
| Draft general specification | [APATCH-SPEC-001 — Patch Workflow and Quality Orchestrator](active/spec-apatch-orchestrator.md) |
| Draft first-priority sub-specification | [APATCH-SUB-001 — Workflow Control, Patch Ordering, and Sequences](active/subspecs/subspec-01-workflow-control.md) |
| Draft execution-history sub-specification | [APATCH-SUB-002 — Execution History and Repository Reconciliation](active/subspecs/subspec-02-state-history-audit.md) |
| Draft feature-session sub-specification | [APATCH-SUB-003 — Feature Sessions and Context-Aware Execution](active/subspecs/subspec-03-feature-session-planning.md) |
| Draft operational-workflow sub-specification | [APATCH-SUB-004 — Operational Workflows, Activity Dashboard, and Stable Checks](active/subspecs/subspec-04-operational-workflows.md) |
| Advisory implementation plan | [APATCH-PLAN-001](plans/apatch-orchestrator-implementation-plan.md) |
| Advisory feature-session plan | [APATCH-PLAN-003](plans/feature-session-context-aware-implementation-plan.md) |
| Advisory operational-workflow plan | [APATCH-PLAN-004](plans/operational-workflows-implementation-plan.md) |
| Completed or archived specifications | None |
| Implemented slices in inspected source | P0.1–P1.2, including self-contained ZIPs, `handoffSeq`, tool-wide progress, `info=PROGRESS`, operation journal, `11 [AUD]`, and `CHECKS_CHANGED_WORKTREE` recovery |
| Prepared in this delivery | SUB-004 WM-01 — recorded cross-project activity in `AUD` (source/test candidate; release unverified) |
| Next operational stages | SUB-004 WM-02 project-local base override; WM-03 guarded local macros; WM-04 stable-check policy; WM-05 publication macros |

Until formal acceptance, [Usage](../USAGE.md) and [Architecture](../ARCHITECTURE.md) describe implemented behavior. Numeric `2 [BAP]` remains for legacy JSON compatibility (AC-54 retirement incomplete). The clean source snapshot inspected for SUB-004 is `9f256d786d29d4121ea0116758af85a903d9636a` (2026-10-26 17:21 UTC); the WM-01 modifications are a separate candidate, not evidence of installation or merge. Feature Sessions, workflow macros, project-specific base overrides, automatic check recovery, secure Git patch formats, scheduled check adapters, and P2/P3 remain proposed until their independent acceptance.

## Planned organization

- `active/spec-<capability>.md`: a focused normative specification with scope, behavioral rules, invariants, and testable acceptance criteria.
- `active/subspecs/<focused-area>.md`: optional subordinate specifications for larger capabilities.
- `plans/<capability>-implementation-plan.md`: a separate advisory, staged plan for implementing an approved specification.
- `archive/`: historical specifications after explicit completion or supersession, if needed.

Create directories when the first actual document needs them; avoid empty scaffolding.

## Lifecycle

1. Identify one owning capability and its current behavior using source code, tests, and user-visible documentation.
2. In an explicitly requested **GENSPEC** stage, define the scope, non-goals, inputs/outputs, safety and recovery invariants, state transitions, and acceptance tests.
3. Prepare a separate plan with small independent increments and test checkpoints. Plan sequencing does not by itself authorize implementation.
4. On later **DEFAULT** implementation requests, make changes for the explicitly selected stage and record completion evidence. Update the normative spec if accepted behavior changes.
5. Under an explicitly requested **REVIEW**, assess code against the owning specification and record findings without implicit modifications.
6. Mark a specification complete or archived only with evidence and a deliberate lifecycle update.

Avoid duplicating CLI help or the README. Link to [Installation](../INSTALLATION.md), [Usage](../USAGE.md), [Architecture](../ARCHITECTURE.md), and [Development](../DEVELOPMENT.md) for descriptive details.
