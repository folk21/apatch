---
type: Implementation Guide
title: 'RE-05 — Retention, Export and Recovery: Task Implementation Plan (Draft)'
description: Advisory RE-05 implementation plan, dependencies, verification, and recovery steps.
document_role: task_plan
parent: subspec.md
spec_status: draft
plan_status: advisory
task_id: RE-05
task_type: GEN_CODE
area: CODE
rtype: DEVELOP
feature_ids:
- REVIEW.RETENTION_EXPORT
---
# RE-05 — Retention, Export and Recovery: Task Implementation Plan (Draft)

- **Status:** ADVISORY / DRAFT; **area:** `CODE`; no implementation authorization is implied.
- **Normative task:** [subspec.md#re-05](subspec.md#re-05).
- **Sub-spec:** [subspec.md](subspec.md).
- **Dependencies:** [RE-04](subspec.md#re-04) (candidate implementation; acceptance not inferred).
- **Verified baseline:** `apatch_files.txt` snapshot `c518880c1c065be10ed267d5dba763e6bebdaa07`, 2026-11-20 05:06 UTC; installed/runtime behavior is not independently verified.

## Ownership and verification entry points

- **Existing code:** `apatch_lib/review_retention.py`, `apatch_lib/review_artifacts.py`, `apatch_lib/code_review.py`, `apatch_lib/configuration/loaders.py`.
- **Existing tests:** `tests/test_review_retention.py`, `tests/test_code_review.py`, `run_tests.sh`, `tools/specs/validate_state.py`.
- **Source updates:** Scope any future changes to this task; reconcile existing modules and test names with a fresh checkout before implementation. The historical source plan below may name old façades such as `apatch_lib/model.py`; project YAML validation now belongs to `apatch_lib/configuration/loaders.py`.
- **Recovery:** Unverified or stale review evidence must never authorize `CMT` or GitHub operations; retain the current fail-closed, non-destructive behavior.

## Stage-specific implementation details (original advisory plan)


**Dependencies:** RE-04 merged candidate code in the supplied `main` snapshot,
project review-policy agreement, verified manifest schema and read-only
retrieval helpers. No new action number, external dependency or migration.

| Owner | Implemented candidate work |
| --- | --- |
| `apatch_lib/model.py` | Add strict opt-in toggle and bounded count/size/age YAML policy, with safe defaults. |
| `apatch_lib/review_retention.py` (new) | Lock private storage, validate full run inventories/digests, select eligible terminal runs, journal/resume safe deletions, provide explicit default-preview pruning and consent-gated metadata-only export. |
| `apatch_lib/review_artifacts.py` | Reserve count/byte quota and clean up eligible old artifacts under the same project-local lock before creating each new enabled-capture run. |
| `apatch_lib/code_review.py` | Pass policy and provider count to capture; preserve checked-snapshot and review gates. |
| `tests/test_review_retention.py` (new), `tests/test_code_review.py` | Exercise standalone retention, export, tampering, concurrency, partial failure recovery and a synthetic Git REV lifecycle. |
| `run_tests.sh`, `tests/test_spec_state.py` | Include selected focused regressions and move only the selected review-evidence stage checkpoint at the developer-directed boundary. |
| `docs/USAGE.md`, `docs/ARCHITECTURE.md`, SUB-006, plan and index | Describe opt-in deletion, safe recovery, export limitations and acceptance boundaries. |

**Execution sequence:**

1. Load project YAML before `REV`; strict schema limits prevent accidental
   policy activation. Existing unchecked contexts and all modes remain intact.
2. After successful CHK/snapshot guards, ensure private ignored reviews
   directory; open a no-follow exclusive `.retention.lock` under it.
3. When `review_retention_enabled`, inspect at most 512 store entries; for each
   24-hex review directory require 0700 permissions, a terminal manifest and
   complete expected 0600 regular-file inventory, no hardlinks, and matching
   stored sizes/SHA-256. Count protected unknown runs toward the run quota.
4. Use stable oldest-first order to choose runs older than the age limit or
   needed to satisfy count/byte budgets, including the upcoming run reservation.
   Protected entries cannot be removed; if they block allocation, abort before
   provider launch. In dry-run return the proposed deletions without unlinking.
5. Before deleting eligible data, write and fsync a bounded per-run pruning
   intent journal with exact expected names, lengths and hashes; rename the
   run to the reserved `pruning-<24-hex>` namespace. Revalidate remaining
   members, unlink only listed files, then the intent journal and empty run.
   Later explicit maintenance resumes a recognized, still-valid partial intent.
   Unexpected files or hash changes preserve the run for manual repair.
6. For an explicit diagnostic export, require `consent=True`, open and verify
   the exact run under the same lock and emit at most 8 KiB of metadata-only
   JSON. Do not expose the checked Git snapshot, file paths, messages or logs;
   the caller explicitly owns any subsequent external transmission.
7. Capture and verdict persistence proceed through existing `REV`. A missing
   or expired artifact never rewrites CHK or a historical PASS; new evidence
   requests requiring it remain blocked. An interrupted provider stays STARTED
   or FAILED, with no automatic model retries or charges.

**Negative/recovery cases:** Unsafe/missing/symlinked storage or lock,
malformed provider entry, duplicate/unlisted member, hardlink, truncated stdout,
modified SHA, `STARTED` manifest, disk-full or write/unlink failure, concurrent
maintainers, deleted export target, and interrupted or malicious pruning
journals. Retain unknown evidence, do not infer success, and require explicit
operator review where automatic recovery cannot prove provenance.

**Verification:**
`python3 -B -m unittest tests.test_review_retention -v`,
`python3 -B -m unittest tests.test_code_review.CodeReviewTests.test_retention_enabled_prunes_old_completed_review_before_next_capture -v`,
`sh ./run_tests.sh`, `sh ./run_rare_checks.sh`,
`python3 tools/specs/validate_state.py`, `python3 -m compileall -q apatch_lib tests`,
`sh -n run_tests.sh` and ZIP metadata/integrity checks.
The filtered snapshot excludes the installed global `apatch.conf`; any
reconstructed-checkout run must disclose the local substitute. Linux checks
never count as macOS verification.

**Acceptance:** SUB-006 RE-05-A–D, above negative/recovery matrix, no regression
in required-review commit or GitHub gates, actual command results and
independent developer acceptance. Do not archive SUB-006 before acceptance.