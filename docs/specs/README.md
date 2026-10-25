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
| Expedited implemented slice | P0.4a0 — Single-handoff `opSeq`, shared `skipApproves`, fail-stop reporting, and basic console outcome labels |
| Next planned stages | P0.3c — Self-contained ZIP and apply-before-branch migration; P0.4a — Remaining detailed console-outcome and remote-uncertainty work |

Until a specification is formally accepted, [Usage](../USAGE.md) and [Architecture](../ARCHITECTURE.md) describe the existing implementation. P0.1 (`STS` and next-action suggestions), P0.2 (project review approval), P0.2b (project CI policy), P0.2c (explicit unique handoff selection), P0.2d (feature-branch creation guard), P0.2e (historical PR revision safety), P0.2f (bounded GitHub read retries and identity reuse), P0.3a/b (created-patch ordering and reserved ZIP metadata transport), and **expedited P0.4a0 (single-handoff `opSeq` with `skipApproves`, fail-stop handling, and basic outcome labels)** have implementation and test coverage. **P0.3c (self-contained ZIP parameters, optional cached handoff, `APL` before `BRN`, retirement of `BAP`) is not implemented; the CLI still requires an explicit JSON handoff and supports the legacy branch-first flow.** The full console-outcome/uncertain-remote contract of P0.4a and multiple distinct ZIPs in one sequence (P0.4b) remain pending. Cross-project `info=PROGRESS` and JSON activity ledgers (P0.5a/b), `AUD`, detailed per-target journaling, and Git-format patches are also **not yet implemented**. This status summary does not itself authorize later stages.

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
