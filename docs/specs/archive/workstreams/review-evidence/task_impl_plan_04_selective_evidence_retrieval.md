---
type: GEN_CODE
title: 'RE-04 — Selective Evidence Retrieval: Task Implementation Plan (Draft)'
description: Advisory RE-04 implementation plan, dependencies, verification, and recovery steps.
area: CODE
runType: DEVELOP
---
# RE-04 — Selective Evidence Retrieval: Task Implementation Plan (Draft)

**Archive note (2026-11-24):** The scoped SUB-006 task was accepted by developer direction. This original advisory plan is retained as historical implementation guidance; it does not authorize new changes or establish GitHub publication.

- **Status:** ADVISORY / DRAFT; **area:** `CODE`; no implementation authorization is implied.
- **Normative task:** [subspec.md#re-04](subspec.md#re-04).
- **Sub-spec:** [subspec.md](subspec.md).
- **Dependencies:** [RE-03](subspec.md#re-03) (candidate implementation; acceptance not inferred).
- **Verified baseline:** `apatch_files.txt` snapshot `c518880c1c065be10ed267d5dba763e6bebdaa07`, 2026-11-20 05:06 UTC; installed/runtime behavior is not independently verified.

## Ownership and verification entry points

- **Existing code:** `apatch_lib/review_evidence_api.py`, `apatch_lib/review_artifacts.py`, `apatch_lib/review_normalizer.py`.
- **Existing tests:** `tests/test_review_evidence_api.py`, `tests/test_code_review.py`, `run_tests.sh`, `tools/specs/validate_state.py`.
- **Source updates:** Scope any future changes to this task; reconcile existing modules and test names with a fresh checkout before implementation. The historical source plan below may name old façades such as `apatch_lib/model.py`; project YAML validation now belongs to `apatch_lib/configuration/loaders.py`.
- **Recovery:** Unverified or stale review evidence must never authorize `CMT` or GitHub operations; retain the current fail-closed, non-destructive behavior.

## Stage-specific implementation details (original advisory plan)


**Dependencies:** RE-03 code in the clean supplied snapshot, normalized finding IDs and private raw/normalized manifests; no external LLM tool dispatcher. **Owner:** `apatch_lib/review_evidence_api.py` (new); documentation in `docs/USAGE.md`, `docs/ARCHITECTURE.md`, this plan and SUB-006; stage checkpoint and tests in `docs/specs/STATE.json`, `tests/test_spec_state.py`, `tests/test_review_evidence_api.py`, `run_tests.sh`.

**Implementation sequence:**

1. Bind a read-only `ReviewEvidenceSession(root, review_id, expected_snapshot, snapshot_reader)` to a single review ID and checked repository snapshot. Validate 24-hex IDs, context line bounds and configurable per-session request/byte quotas. Caller-owned snapshot reader SHALL return the same five-field tuple used by `code_review._snapshot`; the adapter does not compute or mutate Git state itself.
2. Open the trusted root and subsequent `.apatch/reviews/<review_id>` directories using `os.open` with `dir_fd`, `O_DIRECTORY` and `O_NOFOLLOW`. Require private run directory and regular `0600` evidence files. Limit manifest/normalized sizes, stream raw hash verification without loading multi-megabyte logs into memory, reject symlink replacements and malformed metadata.
3. For each configured normalized scanner report, verify provider identity, raw byte count/digest, normalized SHA-256 and the saved five-field snapshot. Require terminal `COMPLETED` manifest and a unique finding ID; allow findings from a blocking scanner only as **diagnostic** data. Any invalid or incomplete artifact returns `REVIEW_EVIDENCE_UNKNOWN` without an LLM call.
4. Walk each source-path component with no-follow directory descriptors; prohibit private runtime or Git paths. Read at most 1 MiB of a regular UTF-8 file, select ±`context_lines` (at most 20), compare the exact pre/post Git snapshot and source `fstat`, and include bounded SHA-256 provenance in a canonical JSON result.
5. Account for every valid request, enforce per-result and cumulative byte limits and reject output overflow rather than silently truncating source lines. The adapter remains an internal data-only API: no CLI action, shell command, automatic external disclosure or model tool-routing is introduced.

**Independent tests:** `python3 -B -m unittest tests.test_review_evidence_api -v` with synthetic private storage; `python3 -B -m unittest tests.test_review_context tests.test_review_normalizer tests.test_code_review -v`, `python3 tools/specs/validate_state.py`, then `sh ./run_tests.sh` and `sh ./run_rare_checks.sh` where the incomplete snapshot supports them. Cover SHA tampering, symlinks in each path component, malicious IDs, missing/double findings, oversized/binary/changed source, quota exhaustion, partial/failed manifests, stale snapshots and absence of subprocess calls. Negative tests must not create a real PR or mutate a real developer repository.

**Recovery and failure:** No mutation of artifacts or Git is attempted. The correct recovery for missing/stale evidence is to run a new explicit CHK/REV, not to accept stale data or silently fetch another path. When an artifact has been deleted or modified, report `UNKNOWN`; previously recorded independent CHK is not rewritten. Source snapshots and budget counters are in-memory, never persisted as new application history.

**Acceptance:** SUB-006 RE-04-A–D, focused tests, required commands, actual check results and independent developer review. No migration, new dependencies or new action ID.