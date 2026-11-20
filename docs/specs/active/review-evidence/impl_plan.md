# APATCH-PLAN-006 — Review Evidence Pipeline: Workstream Integration Plan (Draft)

**Status:** ADVISORY / DRAFT. **Owner:** [APATCH-SUB-006](subspec.md). **Parent:** [APATCH-SPEC-001](../spec-apatch-orchestrator.md).

**Current checkpoint:** RE-05 / READY_FOR_REVIEW; candidate implementations RE-01–RE-05 remain unaccepted. Existing historical plan source cites the 2026-11-05 snapshot; the newest supplied complete text snapshot is 2026-11-18 `main` at `3538c08a033eb31d7cffcbb96c4e87212aa9460d`, not a verified current checkout.

## Architecture and dependencies

The existing `REV` implementation, policy loader, artifact storage and normalization are wired through `apatch_lib/code_review.py`, `apatch_lib/configuration/loaders.py`, `apatch_lib/review_artifacts.py`, `apatch_lib/review_normalizer.py`, `apatch_lib/review_context.py`, `apatch_lib/review_evidence_api.py` and `apatch_lib/review_retention.py`. Review evidence remains private local runtime state. No task changes merge, approval, or CI gates. Historical stage-specific implementation plans were moved intact into the paired task plans; reconcile old owner references against current source before a future implementation step.

## Task types and verification policy

`GEN_CODE` tasks (RE-01–RE-05) own product behavior and module contracts;
`UPD_DOCS` (RE-06) owns documentation synchronization but not `contract.md`;
`GEN_TESTS` (RE-07) owns the final acceptance test matrix and canonical CHK.
Intermediate implementation safety checks must still run when needed; a
proposed deferred CHK workflow cannot override configured Git/CI/review gates.

## Task sequence and handoff

1. **RE-01 — Private Bounded Raw Evidence Capture:** [requirements](task_01_raw_evidence_capture.md) · [implementation plan](task_impl_plan_01_raw_evidence_capture.md). Establish private evidence capture and strict failure behavior.
2. **RE-02 — Structured Adapter Normalization:** [requirements](task_02_structured_normalization.md) · [implementation plan](task_impl_plan_02_structured_normalization.md). Depends on the prior candidate stages; verify live evidence before relying on it.
3. **RE-03 — Compact Context for LLM:** [requirements](task_03_bounded_llm_context.md) · [implementation plan](task_impl_plan_03_bounded_llm_context.md). Depends on the prior candidate stages; verify live evidence before relying on it.
4. **RE-04 — Selective Evidence Retrieval:** [requirements](task_04_selective_evidence_retrieval.md) · [implementation plan](task_impl_plan_04_selective_evidence_retrieval.md). Depends on the prior candidate stages; verify live evidence before relying on it.
5. **RE-05 — Retention, Export and Recovery (`GEN_CODE`):** [requirements](task_05_retention_export_recovery.md) · [implementation plan](task_impl_plan_05_retention_export_recovery.md). Depends on prior candidate stages; verify live evidence before relying on it.
6. **RE-06 — Documentation Synchronization (`UPD_DOCS`):** [requirements](task_06_documentation_sync.md) · [implementation plan](task_impl_plan_06_documentation_sync.md). Synchronize public docs; code-owned `contract.md` remains part of RE-01–RE-05.
7. **RE-07 — Review Evidence Acceptance Tests (`GEN_TESTS`):** [requirements](task_07_review_acceptance_tests.md) · [implementation plan](task_impl_plan_07_review_acceptance_tests.md). Reconcile tests for RE-01–RE-05 and run final canonical `CHK`; proposed run type `GEN_FINAL` requires independently configured support and live publication guards.

## Workstream gates and verification

Each task must be independently reviewable against its normative acceptance oracles. RE-07 owns final test-suite reconciliation. Run task-specific safety tests when changes require them and `python3 tools/specs/validate_state.py`; attempt `sh ./run_tests.sh` and `sh ./run_rare_checks.sh` where the complete checkout supports them, disclosing missing `apatch.conf` or platform limitations. The selected RE-05 task and plan require independent review before developer acceptance. Neither checks nor the ZIP overlay advance SDD acceptance.

## Stage order / sign-off

`RE-01 -> RE-02 -> RE-03 -> RE-04 -> RE-05 -> RE-06 -> RE-07`. Do not claim any later stage complete from RE-01 tests. Before moving the selected checkpoint, record review evidence and obtain developer direction. Archive SUB-006 with its entire plan only after all scoped stages are accepted, then reconcile index, umbrella and checkpoint. SUB-003 and SUB-004 remain planned, not accepted. Their acceptance is independent.
