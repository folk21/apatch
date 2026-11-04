# APATCH-PLAN-006 — Review Evidence Pipeline Implementation Plan

**Status:** ADVISORY / DRAFT. **Normative owner:** [APATCH-SUB-006](subspecs/subspec-06-review-evidence-pipeline.md). **Parent:** [APATCH-SPEC-001](spec-apatch-orchestrator.md).

**Current focus:** RE-02 candidate implementation on the RE-01 candidate baseline, both awaiting developer acceptance; RE-03–RE-05 remain proposals. The RE-01 merge result and newest post-merge repository source have not been independently verified. The previous SUB-004 WM-04 and SUB-003 FS-06 checkpoints remain ON_HOLD and unaccepted. The inspected source baseline is the 2026-11-03 `apatch_files.txt` snapshot at `16038c5e3de465d282af3b43f3c8c2e1c35e121c`, with 132 contents out of 136 tracked files; `apatch.conf`, `.apatch/config.yaml`, `apatch`, and `.DS_Store` were omitted. Recheck against a newer full checkout before any merge.

## Architecture review and dependencies

Existing seams: `apatch_lib/code_review.py` owns the `REV` executor, snapshot drift gates, diff bundling and verdict parsing; `apatch_lib/model.py` owns bounded project YAML parsing; `apatch_lib/local_ignore.py` + `apatch_lib/core/paths.py` own ignored runtime paths; `apatch_lib/workflow.py` owns phase and required-review gates; `tests/test_code_review.py` covers a real local synthetic Git lifecycle. These seams are suitable for incremental extension without changing `Workflow` or GitHub integration.

Limitations identified: legacy `Popen.communicate()` retains all stdout/stderr in memory until exit; script stderr and success details are not retained; nonzero script exits abort immediately, preventing later LLM interpretation; exit zero has no machine-readable scanner result; no normalizer, stable finding ID, bounded model context or retention policy exists. Avoid coupling the evidence store to workflow journal internals or equating model verdict to scanner policy.

## RE-01 — Raw evidence capture (implemented candidate)

**Dependencies:** Current `CHK`/`REV` snapshot and `.apatch` runtime ignore contracts. **Files:**

| File | Work |
| --- | --- |
| `apatch_lib/model.py` | Add strict schema-v1 defaults and range validation for capture switch and per-provider byte bound. |
| `apatch_lib/core/paths.py` | Register `.apatch/reviews` as an ignored runtime directory. |
| `apatch_lib/review_artifacts.py` (new) | Create a private, unique local run; atomically persist a JSON manifest; concurrently drain stdout/stderr to private files; enforce combined bytes, deadlines and SHA-256; retain failed results. |
| `apatch_lib/code_review.py` | Use capture only when opted in, retain legacy behavior otherwise, and publish a relative manifest path on successful verdict; continue strict CHECK snapshot protection. |
| `tests/test_code_review.py` | Verify large output, stderr, hashes, file modes, timeout/overflow, nonzero exit, LLM JSON, symlink refusal and unchanged commit gate. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md` | Document supported settings, stored data, safety limits and the distinction between capture and future normalization. |
| `docs/specs/STATE.json`, `docs/specs/README.md`, umbrella plan | Select RE-01 without promoting or accepting earlier scopes; link the new normative spec and this plan. |

**Algorithm:** Validate CHK and snapshot; create private ignored run; write `STARTED` manifest; for each reviewer launch argv in its existing cwd, write diff/prompt to stdin, concurrently read and count stdout/stderr, spool only bounded bytes to disk and retain up to 256 KiB for LLM JSON parsing; terminate process group on byte/time breach; record exit/truncation and hashes, atomically replace manifest; recheck Git snapshot after each provider; apply existing verdict rules; save checkpoint only on verified final result; finish manifest as `COMPLETED` or `FAILED`.

**Failure/recovery:** Output overflow and timeouts block with partial retained evidence; malformed stdout never authorizes PASS; unsafe ignored paths abort before provider launch; no automatic retries, commit, push or merge. An interrupted process can leave `STARTED` evidence that must be considered incomplete and is never a PASS. A failed checkpoint persistence must not fabricate a successful review.

**Commands / evidence:** `python3 -B -m unittest tests.test_code_review -v`, `sh ./run_tests.sh`, `sh ./run_rare_checks.sh`, `python3 tools/specs/validate_state.py`; on unavailable baseline config, disclose a temporary local test substitute and do not claim byte-identical baseline verification. Check `git status --porcelain`, `git check-ignore`, output file permissions and that no raw stream is copied into the application log. Linux tests do not establish macOS behavior.

**Acceptance:** SUB-006 RE-01-A through RE-01-E and RE-01 acceptance matrix, with actual test results recorded at handoff. Developer sign-off remains outstanding.

## RE-02 — Structured analyzer result adapters (candidate implementation)

**Dependencies:** RE-01 code available from the prior overlay; acceptance/merge not verified. The candidate is conditional until the current full checkout is reconciled. Real tool-version interoperability remains a release verification item. **Owner:** new `apatch_lib/review_normalizer.py` (provisional), coordinated through `code_review.py` and `model.py` only as needed.

1. Define an independently versioned analyzer envelope with command outcome, scanner identity, format, raw path reference and declared blocking status. Never infer success from a wrapper exit code alone.
2. Write type-specific parse functions for SARIF 2.1.0 and supported JSON outputs (Ruff, Bandit, Semgrep). Select format explicitly; avoid heuristics from arbitrary text. Bound input bytes, JSON nesting, findings and message length before parsing.
3. Normalize severity, `file`/`line`, rule, source, raw hash, scanner status and stable finding ID. Validate paths against the repository; prohibit absolute and `..` paths, remote URLs as local evidence, symlink traversal and implicit file opening. Merge duplicates while preserving original evidence IDs.
4. Extend YAML with additive `required`/`advisory` scanner policy and a structured result location only after freezing schema. Keep legacy script exit-code semantics without opt-in. Define an explicit `UNKNOWN` on missing/truncated/failed required scanners and prohibit LLM override of mandatory blockers.
5. Tests: synthetic Git integration plus fixture files for all claimed formats, malicious/symlink paths, mixed failures, duplicate findings, malformed envelopes, enormous reports, missing executable, scan output modified after hashing and wrapper-exit ambiguity. Keep logs bounded.

**Implemented file ownership:** `apatch_lib/model.py` validates opt-in reviewer
scanner policies; `apatch_lib/review_normalizer.py` implements explicit
Ruff/Bandit/Semgrep/SARIF adapters, bounded JSON tree validation, deduplication
and verdict computation; `apatch_lib/review_artifacts.py` re-reads SHA-256
verified raw stdout and stores a private normalized derivative and manifest
index; `apatch_lib/code_review.py` wires this through the existing snapshot
and fail-closed checkpoint gates. `tests/test_review_normalizer.py` owns
format/attack fixtures and `tests/test_code_review.py` exercises synthetic
Git review/commit admission. `run_tests.sh` adds selected RE-02 regressions;
`docs/USAGE.md`, `docs/ARCHITECTURE.md` describe the opt-in contract.

**Execution:** One wrapper's stdout contains a versioned JSON envelope;
each scanner's configured ID/format/required flag is reconciled with its
individual result. A successful status is cross-checked with actual findings;
scanner errors, missing required scanners, truncated output or invalid bytes
cannot produce PASS. Duplicates retain all source IDs. Manifest remains a
private local reference and raw evidence is never transmitted to an LLM. A
trusted wrapper still owns truthful scanner execution; no command attestation
is claimed. Existing `script`/`llm` mode and operation IDs remain unchanged.

**Focused checks:** `python3 -B -m unittest tests.test_review_normalizer -v`,
`python3 -B -m unittest tests.test_code_review -v`,
`python3 tools/specs/validate_state.py`, and full suites where the recovered
snapshot supports them. When current `main`, launcher or global config are
missing, revalidate on a real post-merge checkout before publication.

**Recovery:** Never delete raw RE-01 artifacts on parse failure. Mark adapter status unknown/failed, block as policy requires, and permit explicit rerun on the checked snapshot; do not auto-repeat paid models.

**Acceptance:** SUB-006 RE-02-A–C plus negative and partial-input fixtures; full focused and canonical suites.

## RE-03 — Bounded LLM context (second stage after RE-02)

**Dependencies:** RE-02 accepted; proven severity policy; explicit outbound-data consent. **Owners:** provisional `apatch_lib/review_context.py`, `code_review.py`, `model.py`, documentation and focused `tests/test_code_review.py` or new `tests/test_review_context.py`.

1. Define deterministic `review-summary.json` schema with snapshot identifier, tool result counts, unknown/failed status, selected finding IDs, severities, redacted file/line snippets, and `truncated`/`incomplete` flags.
2. Derive changed-line ranges from the **same** validated diff. Prioritize critical/security findings, then changed-line findings, while recording the count and severity of anything omitted. A required finding that cannot fit the budget shall cause ESCALATE rather than a silent drop.
3. Introduce explicit `review_llm_context_mode: diff|summary` opt-in with strict `max_bytes` (provisional names pending RE-03 design). Build the exact model input in a bounded file or stdin stream; never attach raw outputs or unbounded source. Redact known secret patterns by rule, but treat the summary as sensitive regardless.
4. Validate source snapshot immediately before and after model invocation; reject mixed revisions and invalid JSON verdicts. A model can escalate or request remediation but cannot override a failed required scanner.
5. Test exact prompt bytes and budget, deterministic ranking and hashing, severe-finding overflow, secret fixtures, unsupported outputs, network not called without explicit approval and required-review commit gate.

**Recovery:** Incomplete summary or missing evidence blocks model-dependent PASS. Rerun RE-02 normalization from immutable local raw evidence only after verifying hashes and snapshot; otherwise request an explicit new CHK/REV.

**Acceptance:** SUB-006 RE-03-A–C.

## RE-04 — Read-only selective evidence lookup (third stage)

**Dependencies:** RE-03, stored finding-to-source mappings. **Owners (provisional):** `apatch_lib/review_evidence_api.py`, `review_artifacts.py`, `review_context.py`, tests and CLI usage docs.

Introduce `get_review_evidence(review_id, finding_id, context_lines)` as a bounded internal read-only adapter, **not** an arbitrary shell executor. Require stable known IDs, checked snapshot and raw SHA256. Resolve paths against private storage without symlink traversal, cap context lines, bytes and call count, and provide precise `UNKNOWN` when evidence is missing. Mock LLM tool requests and ensure traversal, stale files, race/TOCTOU and repeated retrieval cannot escape budgets.

## RE-05 — Retention and export (fourth stage)

**Dependencies:** RE-04, reviewed privacy and operational policy. **Owners (provisional):** `review_artifacts.py`, new or existing CLI inspection module, `model.py`, tests and docs.

Introduce count/age/size quotas with explicit pruning, private advisory lock and never delete unknown user files. Export only explicit redacted summary references, not raw logs by default. Model interruptions, concurrent runs, disk-full errors, partial manifests, stale hashes and manual deletions shall be tested. No implicit background polling, retries, remote writes or forced cleanup.

## Stage order / sign-off

`RE-01 -> RE-02 -> RE-03 -> RE-04 -> RE-05`. Do not claim any later stage complete from RE-01 tests. Before moving the selected checkpoint, record review evidence and obtain developer direction. Archive SUB-006 with its entire plan only after all scoped stages are accepted, then reconcile index, umbrella and checkpoint. Existing SUB-003 / SUB-004 acceptance is independent.
