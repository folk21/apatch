---
type: GEN_CODE
title: 'RE-02 — Structured Adapter Normalization: Task Implementation Plan (Draft)'
description: Advisory RE-02 implementation plan, dependencies, verification, and recovery steps.
area: CODE
runType: DEVELOP
---
# RE-02 — Structured Adapter Normalization: Task Implementation Plan (Draft)

- **Status:** ADVISORY / DRAFT; **area:** `CODE`; no implementation authorization is implied.
- **Normative task:** [subspec.md#re-02](subspec.md#re-02).
- **Sub-spec:** [subspec.md](subspec.md).
- **Dependencies:** [RE-01](subspec.md#re-01) (candidate implementation; acceptance not inferred).
- **Verified baseline:** `apatch_files.txt` snapshot `c518880c1c065be10ed267d5dba763e6bebdaa07`, 2026-11-20 05:06 UTC; installed/runtime behavior is not independently verified.

## Ownership and verification entry points

- **Existing code:** `apatch_lib/review_normalizer.py`, `apatch_lib/review_artifacts.py`, `apatch_lib/code_review.py`, `apatch_lib/configuration/loaders.py`.
- **Existing tests:** `tests/test_review_normalizer.py`, `tests/test_code_review.py`, `run_tests.sh`, `tools/specs/validate_state.py`.
- **Source updates:** Scope any future changes to this task; reconcile existing modules and test names with a fresh checkout before implementation. The historical source plan below may name old façades such as `apatch_lib/model.py`; project YAML validation now belongs to `apatch_lib/configuration/loaders.py`.
- **Recovery:** Unverified or stale review evidence must never authorize `CMT` or GitHub operations; retain the current fail-closed, non-destructive behavior.

## Stage-specific implementation details (original advisory plan)


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