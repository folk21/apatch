# RE-04 — Selective Evidence Retrieval (Draft Task)

- **type:** `GEN_CODE`.
- **Task ID:** `RE-04`.
- **Status:** DRAFT / CANDIDATE IMPLEMENTATION; DEVELOPER ACCEPTANCE PENDING; splitting this document does not grant implementation authorization.
- **Sub-spec:** [APATCH-SUB-006](subspec.md).
- **Task plan:** [Implementation plan](task_impl_plan_04_selective_evidence_retrieval.md).
- **Dependencies:** [RE-03](task_03_bounded_llm_context.md) (candidate implementation; acceptance not inferred).
- **Primary code owners (verified snapshot):** `apatch_lib/review_evidence_api.py`, `apatch_lib/review_artifacts.py`, `apatch_lib/review_normalizer.py`.
- **Relevant existing tests:** `tests/test_review_evidence_api.py`, `tests/test_code_review.py`.

## Normative requirements and acceptance oracles

The acceptance test cases below are requirements. RE-07 owns the final suite reconciliation and canonical CHK execution; task-specific security failures remain blocking during implementation. This task does not authorize bypassing existing runtime checks or publication gates.


**RE-04-A** Expose `ReviewEvidenceSession.get_review_evidence(review_id, finding_id, context_lines)` as a **local, read-only** internal Python interface. The caller SHALL bind the session to a single repository root, review ID, expected checked snapshot and a live snapshot reader. The API SHALL NOT register a new CLI action, execute scripts, invoke a model, perform network access or write application state. Requests SHALL identify an exact existing 24-hex finding ID from a SHA-256-verified normalized report. The completed manifest and normalized result SHALL match the requested review and expected snapshot. A non-PASS scanner result MAY be retrieved for diagnostics, but it SHALL never authorize a PASS or bypass a required scanner gate.

**RE-04-B** Evidence lookup SHALL open `.apatch/reviews/<review_id>/` through file-descriptor-relative, no-follow directory traversal. Review/run directories MUST have mode `0700`; manifest, raw stdout and normalized JSON MUST be private regular files with mode `0600`. The provider's raw stdout byte count/hash and the normalized JSON digest, snapshot, reviewer identity and raw source digest SHALL be reverified for every request. Unknown, ambiguous, malformed, truncated, symlinked, missing or modified evidence SHALL fail closed with `REVIEW_EVIDENCE_UNKNOWN`. A partial or `STARTED`/`FAILED` run SHALL NOT be used for lookup. Manifest hash references are integrity checks, not independent cryptographic attestation against a privileged actor who can replace both file and manifest.

**RE-04-C** Source retrieval SHALL follow only the normalized finding's repository-relative path. `.git` and `.apatch` are prohibited; traversal and symlinked path components SHALL be refused. Each file SHALL be an ordinary UTF-8 text file of at most 1 MiB; a missing finding line or source file SHALL be `UNKNOWN`. An excerpt SHALL include only the specified line and at most 20 surrounding lines in each direction. The response SHALL include review and finding IDs, the original scanner verdict, snapshot SHA-256, relative source path, selected line numbers/text, source content SHA-256, normalized evidence SHA-256 and raw stdout SHA-256. The snapshot reader SHALL match before and after retrieval; a changed file descriptor or checked Git state fails closed. Source excerpts can contain secrets and SHALL NOT be automatically forwarded to any LLM.

**RE-04-D** A session SHALL allow at most 1–8 requests (default 4), with each JSON response capped at 1,024–8,192 bytes (default 8,192) and total output capped at the session's configured 8,192–65,536 bytes (default 16,384). Invalid requests and exhausted budgets SHALL not fetch additional evidence. Valid requests consume a call quota even if the report is missing or oversized. Output construction SHALL remain deterministic and shall never silently truncate a returned source line. Budgets are per in-process session, not a persistent global rate limit; future model tool-routing requires separate authorization and enforcement.

**RE-04 acceptance:** Tests for exact lookup, privacy, SHA-256 and snapshot binding, severity-independent diagnostics, no process/network calls, output and request quotas, malformed/partial manifests, symlinked directories/files, traversal, missing and oversized source, binary input, ambiguous IDs and drift before/after retrieval. `run_tests.sh`, `run_rare_checks.sh` and `tools/specs/validate_state.py` SHALL be attempted and reported. This candidate does not implement an external LLM tool-call dispatcher; that integration requires a separately reviewed disclosure and invocation contract.
