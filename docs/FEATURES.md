# Features

Stable capability IDs identify requirements and traceability, not runtime ZIP fields, automatic acceptance, or deployment. Implementation maturity and references live in [feature cross-reference](specs/feature-cross-ref.yaml).

| Feature ID | Brief description |
| --- | --- |
| `HANDOFF.ZIP_INPUT` | Validated self-contained ZIP metadata, safe extraction and legacy handoff compatibility. |
| `HANDOFF.ZIP_PRODUCER` | Read-only source preflight and verified ZIP artifact production. |
| `WORKFLOW.SEQUENCES` | Stable numbered/mnemonic operations and safe multi-step execution. |
| `WORKFLOW.FEATURE_SESSIONS` | Verified continuation of patch work in one feature branch with explicit publication identity. |
| `WORKFLOW.BUILD_ONLY` | Independent project-defined build commands separate from canonical checks. |
| `PUBLICATION.PR_GUARDS` | Unique exact-revision pull request reuse, review and CI safety. |
| `PUBLICATION.MERGE_SYNC` | Guarded GitHub merge and independent local base sync. |
| `STATE.OPERATION_JOURNAL` | Durable action outcomes and safely recoverable execution history. |
| `STATE.AUDIT` | Read-only reconciliation of repository patch history and uncertain outcomes. |
| `REVIEW.RAW_CAPTURE` | Private bounded output capture and manifest integrity for reviewer execution. |
| `REVIEW.NORMALIZATION` | Structured scanner report normalization and bounded mandatory-scanner policy. |
| `REVIEW.LLM_CONTEXT` | Consent-gated, bounded deterministic reviewer context. |
| `REVIEW.RETRIEVAL` | Selective local read-only finding evidence with private-path and snapshot verification. |
| `REVIEW.RETENTION_EXPORT` | Opt-in protected evidence pruning and consent-gated metadata export. |
