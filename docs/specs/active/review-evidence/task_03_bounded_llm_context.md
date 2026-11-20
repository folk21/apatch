# RE-03 — Compact Context for LLM (Draft Task)

- **type:** `GEN_CODE`.
- **Task ID:** `RE-03`.
- **Status:** DRAFT / CANDIDATE IMPLEMENTATION; DEVELOPER ACCEPTANCE PENDING; splitting this document does not grant implementation authorization.
- **Sub-spec:** [APATCH-SUB-006](subspec.md).
- **Task plan:** [Implementation plan](task_impl_plan_03_bounded_llm_context.md).
- **Dependencies:** [RE-02](task_02_structured_normalization.md) (candidate implementation; acceptance not inferred).
- **Primary code owners (verified snapshot):** `apatch_lib/review_context.py`, `apatch_lib/code_review.py`, `apatch_lib/configuration/loaders.py`.
- **Relevant existing tests:** `tests/test_review_context.py`, `tests/test_code_review.py`.

## Normative requirements and acceptance oracles

The acceptance test cases below are requirements. RE-07 owns the final suite reconciliation and canonical CHK execution; task-specific security failures remain blocking during implementation. This task does not authorize bypassing existing runtime checks or publication gates.


**RE-03-A** Compose a deterministic `review-summary.json` or equivalent from RE-02 evidence plus a bounded reviewed diff. Sort by severity, security impact and changed-line relevance; preserve severe findings or explicitly escalate on budget overflow. Include counts, all tool status categories, truncation flag, stable evidence IDs, snapshot ID, selected excerpts and an explicit byte/token budget.

**RE-03-B** No model SHALL receive raw scanner logs automatically. A configured LLM reviewer SHALL receive only an explicitly configured bounded summary, selected source/diff excerpts, and the untrusted-data instruction. Missing required findings or report truncation SHALL fail closed; never summarize by silently dropping a required security finding. Model output SHALL retain the existing JSON verdict validation and checked-byte binding.

**RE-03-C** Secrets and private paths in raw reports require an explicit project policy for redaction and outbound access. The summary is not presumed secret-free; local-only execution MUST be possible. No HTTP/model call may occur without an explicit reviewer in an invoked `REV` or required guarded workflow.

**RE-03 implementation profile (normative):** A `kind: llm` reviewer MAY set
`input_mode: structured-summary`; the default remains `diff`. This mode SHALL
require `review_artifacts_enabled: true` and the explicit project setting
`review_context_external_consent: true`. The byte budget is
`review_context_max_bytes` (4,096–65,536 inclusive, default 32,768) and SHALL
include the static reviewer instruction prefix as well as the UTF-8 JSON.
`review_context_include_messages` and `review_context_include_diff` SHALL
both default to `false`; each requires external consent when enabled.
Reviewers continue to run in YAML order. Summary-mode LLMs SHALL require
at least one *prior*, successful, structured scanner provider in the current
`REV`. Raw stdout SHALL be checked for integrity before each normalized
report is read; the normalized file SHALL be checked against its manifest
SHA-256, source stdout digest and exact checked snapshot. Missing or stale
reports SHALL abort before the model starts. Prior required scanner failures
or blocking findings still terminate `REV` before later LLMs.

The model context SHALL include a deterministic snapshot digest, HEAD, every
prior scanner status and finding count, severity totals, prioritized stable
finding IDs with path/line/rule/provenance metadata, and explicit omission
counts. Sorting SHALL prioritize severity, then changed-line relevance, then
stable identity. On overflow, low/medium findings MAY be omitted with an
explicit `truncated` flag and count; *no* high/critical finding may be omitted
silently. If severe findings or scanner status cannot fit, abort before model
invocation. When enabled, limited textual finding messages and added diff
lines are the only optional untrusted text. Raw stdout/stderr, manifests,
credentials and entire normalized files SHALL NEVER be appended to the model
input automatically. Per-LLM `<id>.context.json` SHALL be saved as an ignored
private local artifact with digest and byte length indexed in the manifest.
For summary-mode LLMs, `APATCH_REVIEW_CONTEXT` points at a temporary context
file, `APATCH_REVIEW_DIFF` is absent, and the `{diff_file}` compatibility
placeholder resolves to the context file rather than the full diff.
The configured executable is user-trusted, not a sandbox; no automatic secret
redactor can guarantee confidentiality. Enabling text/diff transmission is
explicit consent to potentially disclose source and secrets, even when the
LLM CLI is nominally local. No HTTP call is added by `apatch` itself.

**RE-03 acceptance:** Assert exact context size, no raw-log leakage, deterministic priority, blocked incomplete input, changed-line relevance, model JSON parsing, confidentiality guardrails and required-review commit gate.
