# RE-02 — Structured Adapter Normalization (Draft Task)

- **type:** `GEN_CODE`.
- **Task ID:** `RE-02`.
- **Status:** DRAFT / CANDIDATE IMPLEMENTATION; DEVELOPER ACCEPTANCE PENDING; splitting this document does not grant implementation authorization.
- **Sub-spec:** [APATCH-SUB-006](subspec.md).
- **Task plan:** [Implementation plan](task_impl_plan_02_structured_normalization.md).
- **Dependencies:** [RE-01](task_01_raw_evidence_capture.md) (candidate implementation; acceptance not inferred).
- **Primary code owners (verified snapshot):** `apatch_lib/review_normalizer.py`, `apatch_lib/review_artifacts.py`, `apatch_lib/code_review.py`, `apatch_lib/configuration/loaders.py`.
- **Relevant existing tests:** `tests/test_review_normalizer.py`, `tests/test_code_review.py`.

## Normative requirements and acceptance oracles

The acceptance test cases below are requirements. RE-07 owns the final suite reconciliation and canonical CHK execution; task-specific security failures remain blocking during implementation. This task does not authorize bypassing existing runtime checks or publication gates.


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
