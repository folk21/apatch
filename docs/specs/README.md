# SDD Specification Index

This directory holds proposed normative specifications and implementation plans for `apatch`. Documents marked **DRAFT** are under discussion and do not authorize implementation.

## Status

| Category | Current status |
| --- | --- |
| Accepted normative specifications | None yet |
| Draft general specification | [APATCH-SPEC-001 — Patch Workflow and Quality Orchestrator](active/spec-apatch-orchestrator.md) |
| Draft first-priority sub-specification | [APATCH-SUB-001 — Workflow Control, Patch Ordering, and Sequences](active/subspecs/subspec-01-workflow-control.md) |
| Draft execution-history sub-specification | [APATCH-SUB-002 — Execution History and Repository Reconciliation](active/subspecs/subspec-02-state-history-audit.md) |
| Advisory implementation plan | [APATCH-PLAN-001](plans/apatch-orchestrator-implementation-plan.md) |
| Completed or archived specifications | None |
| Implemented slices | P0.1–P0.5b, including self-contained handoffs, explicit `handoffSeq`, tool-wide progress recording, and read-only `info=PROGRESS` overview |
| Next planned stages | P1.1 — detailed execution journal; P1.2 — global patch audit (`AUD`) |

Until formal acceptance, [Usage](../USAGE.md) and [Architecture](../ARCHITECTURE.md) describe implemented behavior. P0.1–P0.5b have implementation and regression coverage, but are not certified or formally accepted. Numeric `2 [BAP]` remains for legacy JSON compatibility (AC-54 retirement incomplete). Detailed P1 execution history, `AUD`, secure Git patch formats, scheduled checks, and P2/P3 extensions remain future work. A security/reliability refactor preceded P0.5 without changing the draft requirement set.

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
