# APATCH-SUB-006 — Review Evidence Pipeline

**Status:** DRAFT. RE-01–RE-05 are candidate implementations pending independent developer acceptance; only the selected task RE-05 is at `READY_FOR_REVIEW`. The older 2026-11-05 RE-05 baseline remains historical evidence, not the current repository revision.

**Parent:** [APATCH-SPEC-001](../spec-apatch-orchestrator.md). **Plan:** [integration plan](impl_plan.md). **Related:** [SUB-003](../../planned/subspec-03-feature-session-planning.md), [SUB-004](../../planned/subspec-04-operational-workflows.md).

## 1. Objective and boundary

Extend the existing opt-in `13 [REV]` stage to run repository-configured review scripts which may themselves orchestrate lint, static analysis, security scanners, and LLM CLIs. Preserve complete bounded raw evidence locally and supply later LLM reviewers with a compact, auditable, bounded structured context. This is an evidence pipeline inside `apatch`, not an autonomous code-repair or SDD-planning agent.

No new atomic action ID, implicit model invocation, shell interpolation, remote mutation, source mutation, automatic commit, or bypass of the current CHK/REV/CMT/PR policies is authorized. LOOSE remains the default; STRICT/FORCE and explicit numeric/mnemonic `op`, `opSeq`, guarded `goal`, and existing handoffs remain compatible. A reviewer is an explicitly configured trusted executable, not a sandboxed plugin. Models and scanner output are untrusted input, never instructions to `apatch`.

## 2. Existing behavior and invariants

`REV` requires successful `CHK` on the exact pending worktree/index revision, branch, HEAD, and project review policy; the stage is invalidated by a new `CHK` or any drift. Configured providers are ordered (`kind: script|llm`); scripts receive diff on stdin and `APATCH_REVIEW_DIFF`, and currently PASS on exit 0. LLMs receive instructions and bounded diff through stdin, must return explicit validated JSON verdicts, and run outside the target repository. Failure, timeout, an invalid response, or a non-PASS verdict stops following providers. `review_required: true` blocks `CMT` without a fresh overall PASS. GitHub review/CI protections are independent and remain authoritative.

The existing strict output parser limits LLM findings and the full diff input. The existing legacy `REV` invocation remains the compatibility behavior when evidence capture is not enabled. Capture does not change scanner pass/fail semantics; a future structured adapter must not infer that exit 0 means zero findings unless the adapter contract proves it.


## 3. Task index and dependencies

Tasks declare one `type` from `GEN_CODE`, `UPD_DOCS`, and `GEN_TESTS`.
`type` is SDD metadata, not an executable `apatch` option. The final
`GEN_TESTS` task runs canonical `CHK`; earlier code-task verification
requirements remain normative and are reconciled by RE-07.


| Task | Type | Normative scope | Advisory task plan | State |
| --- | --- | --- | --- | --- |
| `RE-01` | `GEN_CODE` | [Private Bounded Raw Evidence Capture](task_01_raw_evidence_capture.md) | [Task plan](task_impl_plan_01_raw_evidence_capture.md) | Candidate; not accepted |
| `RE-02` | `GEN_CODE` | [Structured Adapter Normalization](task_02_structured_normalization.md) | [Task plan](task_impl_plan_02_structured_normalization.md) | Candidate; not accepted |
| `RE-03` | `GEN_CODE` | [Compact Context for LLM](task_03_bounded_llm_context.md) | [Task plan](task_impl_plan_03_bounded_llm_context.md) | Candidate; not accepted |
| `RE-04` | `GEN_CODE` | [Selective Evidence Retrieval](task_04_selective_evidence_retrieval.md) | [Task plan](task_impl_plan_04_selective_evidence_retrieval.md) | Candidate; not accepted |
| `RE-05` | `GEN_CODE` | [Retention, Export and Recovery](task_05_retention_export_recovery.md) | [Task plan](task_impl_plan_05_retention_export_recovery.md) | Selected, ready for review |
| `RE-06` | `UPD_DOCS` | [Documentation Synchronization](task_06_documentation_sync.md) | [Task plan](task_impl_plan_06_documentation_sync.md) | Draft; not started |
| `RE-07` | `GEN_TESTS` | [Review Evidence Acceptance Tests](task_07_review_acceptance_tests.md) | [Task plan](task_impl_plan_07_review_acceptance_tests.md) | Draft; final task |

`RE-01 → RE-02 → RE-03 → RE-04 → RE-05 → RE-06 → RE-07`. Each normative requirement and acceptance oracle lives in its owning task; its detailed implementation design lives only in its paired advisory plan. `RE-05` remains the selected review checkpoint; RE-06 and RE-07 have not begun. No task type is an authorization to modify product code or a claim of acceptance.

## 4. Compatibility and acceptance boundary

RE-01 is additive to current `REV` and has no migration of existing recorded reviews, operation IDs, handoff state or Git history. An external model tool dispatcher remains outside this specification. RE-01–RE-07 remain unaccepted drafts or candidate implementations. RE-07 is responsible for the final test-evidence matrix and canonical checks, not for retroactive approval of any preceding task. Review evidence is not human approval or GitHub status. Each stage requires focused regression evidence, source review and explicit developer acceptance. SUB-003/004 remain planned and unaccepted; switching the SDD focus is not their acceptance.
