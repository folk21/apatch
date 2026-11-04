# APATCH-SUB-006 — Review Evidence Pipeline

**Status:** DRAFT. RE-01 through RE-03 have candidate implementations awaiting independent review and developer acceptance. RE-04–RE-05 remain proposals, not implemented or accepted. RE-03 builds on the prior RE-01/RE-02 ZIP candidates; source after remote merge is unverified.

**Parent:** [APATCH-SPEC-001](../spec-apatch-orchestrator.md). **Plan:** [APATCH-PLAN-006](../subspec-06-review-evidence-pipeline-implementation-plan.md). **Related:** [SUB-003](subspec-03-feature-session-planning.md), [SUB-004](subspec-04-operational-workflows.md).

## 1. Objective and boundary

Extend the existing opt-in `13 [REV]` stage to run repository-configured review scripts which may themselves orchestrate lint, static analysis, security scanners, and LLM CLIs. Preserve complete bounded raw evidence locally and supply later LLM reviewers with a compact, auditable, bounded structured context. This is an evidence pipeline inside `apatch`, not an autonomous code-repair or SDD-planning agent.

No new atomic action ID, implicit model invocation, shell interpolation, remote mutation, source mutation, automatic commit, or bypass of the current CHK/REV/CMT/PR policies is authorized. LOOSE remains the default; STRICT/FORCE and explicit numeric/mnemonic `op`, `opSeq`, guarded `goal`, and existing handoffs remain compatible. A reviewer is an explicitly configured trusted executable, not a sandboxed plugin. Models and scanner output are untrusted input, never instructions to `apatch`.

## 2. Existing behavior and invariants

`REV` requires successful `CHK` on the exact pending worktree/index revision, branch, HEAD, and project review policy; the stage is invalidated by a new `CHK` or any drift. Configured providers are ordered (`kind: script|llm`); scripts receive diff on stdin and `APATCH_REVIEW_DIFF`, and currently PASS on exit 0. LLMs receive instructions and bounded diff through stdin, must return explicit validated JSON verdicts, and run outside the target repository. Failure, timeout, an invalid response, or a non-PASS verdict stops following providers. `review_required: true` blocks `CMT` without a fresh overall PASS. GitHub review/CI protections are independent and remain authoritative.

The existing strict output parser limits LLM findings and the full diff input. The existing legacy `REV` invocation remains the compatibility behavior when evidence capture is not enabled. Capture does not change scanner pass/fail semantics; a future structured adapter must not infer that exit 0 means zero findings unless the adapter contract proves it.

## 3. RE-01 — Private bounded raw evidence capture

**RE-01-A** Project schema-v1 YAML SHALL accept `review_artifacts_enabled` (boolean, default false) and `review_artifact_max_bytes` (integer 65,536–67,108,864, default 8,388,608), rejecting unknown or invalid values. Existing configs without the keys SHALL retain behavior. No implicit network/model calls are introduced.

**RE-01-B** For enabled capture, each explicit `REV` after validated CHK inputs SHALL create a unique private run directory `<root>/.apatch/reviews/review-<random>/`. Storage SHALL be ignored and untracked by Git before writing; the implementation SHALL fail closed for symlinked or otherwise unsafe storage. Directory mode SHALL be `0700`; individual files SHALL be `0600`. Persistent output is sensitive local runtime data, excluded from ZIP overlays and application logs.

**RE-01-C** External reviewer stdout and stderr SHALL be drained concurrently to separate files, without accumulating the full streams in RAM. Their **combined** bytes SHALL not exceed `review_artifact_max_bytes` per provider; exceeding the bound SHALL terminate the process group where supported, retain a truncated partial report, and fail `REV`. The configured timeout and no-source-mutation guards remain mandatory. LLM JSON parsing SHALL never consume more than the prior 262,144-byte stdout limit. Legacy capture-disabled behavior remains unchanged in RE-01.

**RE-01-D** A schema-v1 `manifest.json` SHALL record run identity, exact pre-review snapshot, status (`STARTED`, `FAILED`, `COMPLETED`), and each completed provider's ID/kind, exit status, stdout/stderr basename, byte counts, SHA-256 digests, truncation and timeout flags. It SHALL NOT store the diff, prompt, credentials, or argv. Manifests SHALL be replaced atomically and failed runs SHALL retain available evidence. A successful workflow checkpoint MAY include a relative artifact path; raw data SHALL NOT be embedded in the checkpoint.

**RE-01-E** A nonzero exit, timeout, overflow, missing/inaccessible output, malformed model JSON, or detected source/index/branch/policy drift SHALL never produce PASS. Review artifacts are diagnostics and do not authorize commit. Missing or incomplete manifests are not evidence of success.

**RE-01 acceptance:** Tests prove complete 400+ KiB scripted output capture, independent stderr, private file permissions, correct digests, failed subprocess retention and blocking, overflow and timeout blocking, symlink protection, ignored/untracked output, LLM JSON compatibility, unchanged legacy REV/CHK/CMT behavior, and no real remote actions. The regular and extended test suites and state validator SHALL be attempted before handoff; any unavailable baseline files or environments SHALL be disclosed.

## 4. RE-02 — Structured adapter normalization (candidate implementation)

**RE-02-A** Accept an opt-in reviewer report envelope naming a fixed schema, adapter identity, status (`SUCCEEDED`, `FINDINGS`, `FAILED`, `TIMED_OUT`, `UNKNOWN`), output references and declared input format (`sarif`, `json`, or explicitly labelled plain text). Scanners may be invoked by a single wrapper, but individual tool outcomes MUST remain distinguishable. A wrapper SHALL NOT turn a failed mandatory scanner into PASS merely by exiting 0.

**RE-02-B** Normalize supported JSON/SARIF findings into bounded records with stable local IDs, tool, rule, severity, path, line/range, message, raw evidence reference and snapshot association. Reject malformed/unsafe paths; never execute embedded content or follow links from untrusted reports. Severity mapping and unsupported formats SHALL be explicit. Deduplicate without losing source provenance; retain original raw files.

**RE-02-C** A tool failure, partial report, truncation, unexpected schema, or evidence-integrity mismatch SHALL yield `UNKNOWN` or `ESCALATE`, not PASS. Advisory-only findings may warn if policy allows; mandatory/high-confidence blockers SHALL remain blocking regardless of a subsequent LLM verdict. Define exact project-level blocker policy and backward-compatible defaults before implementation.

**RE-02 implementation profile (normative):** Opt-in `script` reviewers
SHALL declare `report_format: apatch-json-v1` plus 1–16 distinct `scanners`
entries `{id, format, required}`. `review_artifacts_enabled: true` is
mandatory for structured mode. Allowed formats are `ruff-json`, `bandit-json`,
`semgrep-json`, `sarif-2.1.0`; `required` is a mandatory boolean controlled by
project YAML, never scanner stdout. Older reviewer entries retain exit-code
semantics. The trusted script emits a single UTF-8 JSON stdout envelope
`{schema_version: 1, tools: [...]}` with 0–16 named scanner objects containing
`id`, `format`, `status` and `report` on success. Only `SUCCEEDED` with an
empty parsed report and `FINDINGS` with nonempty parsed report are accepted;
`FAILED`, `TIMED_OUT`, `UNKNOWN` omit `report`. A missing scanner is `UNKNOWN`.
Unknown or repeated scanner IDs and mismatched formats are invalid. Wrapper
nonzero exit, truncated raw stdout/stderr, malformed JSON, report errors, an
unsafe path, inconsistent status or failed raw digest blocks `REV` outright.
A `required` scanner that is unknown, failed or timed out SHALL produce
`ESCALATE`; its `high` or `critical` finding SHALL produce `CHANGES_REQUIRED`.
Advisory scanner failures and findings MAY warn without blocking. Existing
`CMT` required-review gate refuses non-PASS. Ruff defaults to `medium`;
Bandit HIGH/MEDIUM/LOW maps to high/medium/low; Semgrep
ERROR/WARNING/INFO maps to high/medium/low; SARIF
error/warning/note/none maps to high/medium/low/info. Raw stdout is bounded
by RE-01; parsed JSON has a 24-level, 50,000-node and 512-finding limit,
strict path/line/rule/message bounds and no symlink following. Reports with
unsupported or missing information fail closed. A deterministic finding ID
and deduplicated provenance with per-scanner source IDs SHALL be saved in a
private `<reviewer>.normalized.json`; its digest SHALL be in the manifest,
with the raw hash and checked snapshot recorded in the normalized report.
Only bounded status/count/path metadata SHALL enter the workflow checkpoint.
Raw logs and normalized findings SHALL NOT be sent to models by this stage.

**RE-02 acceptance:** Synthetic fixtures for Ruff/Bandit/Semgrep/SARIF plus invalid/huge/malicious output, mixed mandatory/advisory statuses, conflicting severity, duplicate findings, manual changed files, and incomplete tools.

## 5. RE-03 — Compact context for LLM (candidate implementation)

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

## 6. RE-04 — Selective evidence retrieval (proposed)

Expose a read-only, bounded `review_id` + `finding_id` lookup of one verified raw excerpt or source slice. Validate path containment without symlink traversal; cap requests, bytes and lines; attach evidence hashes and source snapshots. Requests from the model remain advisory data requests, not command execution or file writes. No implicit tools/network access. Malformed IDs, stale snapshots, deleted artifacts and unexpected file types fail closed. Test traversal, TOCTOU, rate bounds and partial reports.

## 7. RE-05 — Retention, export and recovery (proposed)

Introduce configurable count/size/time retention with conservative defaults, project-local locking and explicit pruning rules that never delete user files or unknown histories. Exports for an external orchestrator SHALL contain only explicitly selected, redacted summaries and evidence references. A missing artifact SHALL not invalidate an independently recorded previously successful CHK, but SHALL prevent any new or attempted replay that requires unavailable report contents. Interrupted captures retain failed/unknown status; no inferred success or automatic retry of LLM charges. Test concurrent invocations, recovery, storage quotas, interrupted manifest writes and secret-safe exports.

## 8. Compatibility and acceptance boundary

RE-01 is additive to current `REV` and has no migration of existing recorded reviews, operation IDs, handoff state or Git history. RE-04–RE-05 require further design and implementation checkpoints; RE-01–RE-03 are unaccepted candidates, not proof of publication or remote merge. Review evidence is not human approval or GitHub status. Each stage requires focused regression evidence, source review and explicit developer acceptance. SUB-003/004 remain active and unaccepted; switching the SDD focus is not their acceptance.
