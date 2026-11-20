# RE-03 — Compact Context for LLM: Task Implementation Plan (Draft)

- **Status:** ADVISORY / DRAFT; no implementation authorization is implied.
- **Normative task:** [task_03_bounded_llm_context.md](task_03_bounded_llm_context.md).
- **Sub-spec:** [subspec.md](subspec.md).
- **Dependencies:** [RE-02](task_02_structured_normalization.md) (candidate implementation; acceptance not inferred).
- **Verified baseline:** `apatch_files.txt` snapshot `3538c08a033eb31d7cffcbb96c4e87212aa9460d`, 2026-11-18 19:41 UTC; installed/runtime behavior is not independently verified.

## Ownership and verification entry points

- **Existing code:** `apatch_lib/review_context.py`, `apatch_lib/code_review.py`, `apatch_lib/configuration/loaders.py`.
- **Existing tests:** `tests/test_review_context.py`, `tests/test_code_review.py`, `run_tests.sh`, `tools/specs/validate_state.py`.
- **Source updates:** Scope any future changes to this task; reconcile existing modules and test names with a fresh checkout before implementation. The historical source plan below may name old façades such as `apatch_lib/model.py`; project YAML validation now belongs to `apatch_lib/configuration/loaders.py`.
- **Recovery:** Unverified or stale review evidence must never authorize `CMT` or GitHub operations; retain the current fail-closed, non-destructive behavior.

## Stage-specific implementation details (original advisory plan)


**Dependencies:** RE-02 candidate source available; remote merge and developer acceptance unverified; explicit external consent. **Owners:** `apatch_lib/review_context.py`, `code_review.py`, `review_artifacts.py`, `model.py`, documentation, `tests/test_review_context.py`, `tests/test_code_review.py` and `run_tests.sh`.

1. Define deterministic `review-summary.json` schema with snapshot identifier, tool result counts, unknown/failed status, selected finding IDs, severities, optional user-consented file/diff text, and explicit truncation counts.
2. Derive changed-line ranges from the **same** validated diff. Prioritize critical/security findings, then changed-line findings, while recording the count and severity of anything omitted. A high/critical finding that cannot fit the budget shall block review rather than be silently dropped.
3. Introduce per-LLM `input_mode: diff|structured-summary`, explicit `review_context_external_consent`, `review_context_max_bytes`, and opt-in text/diff fields. Build the exact model input in a bounded file or stdin stream; never attach raw outputs or unbounded source. No redaction is claimed: text is omitted by default and any allowed text remains sensitive.
4. Validate source snapshot immediately before and after model invocation; reject mixed revisions and invalid JSON verdicts. A model can escalate or request remediation but cannot override a failed required scanner.
5. Test exact prompt bytes and budget, deterministic ranking and hashing, severe-finding overflow, secret fixtures, unsupported outputs, network not called without explicit approval and required-review commit gate.

**Implemented data path:** A summary-mode LLM executes only after one or more
preceding structured `script` reviewers. `ReviewArtifacts.verified_normalized`
opens normalized evidence without following symlinks, checks permissions and
SHA-256 against the manifest, verifies raw stdout as well, and checks source
snapshot identity. `review_context.build_review_context` computes a stable
snapshot digest and per-tool counts, sorts findings by severity/changed-line
relevance, and maintains exact JSON byte budgets. Only high/critical findings
are fail-closed on budget overflow; lower-severity omissions are counted and
marked. Messages/diff excerpts are absent by default. `code_review.run_review`
separates summary-mode model execution from the raw diff temporary file and
passes the exact bounded JSON via stdin. The private `<llm>.context.json` is
hashed and indexed in the manifest. The legacy `diff` reviewer remains
unchanged. `model.load_project_config` rejects missing consent, invalid types
and unsupported modes without executing any tool.

**Independent checks:** `python3 -B -m unittest tests.test_review_context -v`,
`python3 -B -m unittest tests.test_code_review -v`,
`python3 -B -m unittest tests.test_review_normalizer -v`,
`sh ./run_tests.sh`, `sh ./run_rare_checks.sh`,
`python3 tools/specs/validate_state.py`. Tests shall also check malformed
snapshot provenance, symlink and digest drift, blocked pre-scanner LLM,
output omission and high-severity overflow, and no unexpected network calls.
The original snapshot omits `apatch.conf` and the launcher; use temporary
fixture files only and do not claim all test or platform coverage.

**Known boundary:** The existing `REV` stops at a structured scanner's
non-PASS verdict. RE-03 does not attempt LLM triage of a blocking finding;
this remains fail-closed and may require an explicit separate design change.
The executable invoked through `kind: llm` is trusted, not confined; consent
is not a proof of redaction or confidentiality. Retention and read-only
selective retrieval remain RE-05 and RE-04 respectively.

**Recovery:** Incomplete summary or missing evidence blocks model-dependent PASS. Rerun RE-02 normalization from immutable local raw evidence only after verifying hashes and snapshot; otherwise request an explicit new CHK/REV.

**Acceptance:** SUB-006 RE-03-A–C.
