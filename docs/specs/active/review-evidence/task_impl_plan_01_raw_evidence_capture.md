# RE-01 — Private Bounded Raw Evidence Capture: Task Implementation Plan (Draft)

- **Status:** ADVISORY / DRAFT; no implementation authorization is implied.
- **Normative task:** [task_01_raw_evidence_capture.md](task_01_raw_evidence_capture.md).
- **Sub-spec:** [subspec.md](subspec.md).
- **Dependencies:** None.
- **Verified baseline:** `apatch_files.txt` snapshot `3538c08a033eb31d7cffcbb96c4e87212aa9460d`, 2026-11-18 19:41 UTC; installed/runtime behavior is not independently verified.

## Ownership and verification entry points

- **Existing code:** `apatch_lib/review_artifacts.py`, `apatch_lib/code_review.py`, `apatch_lib/configuration/loaders.py`, `apatch_lib/core/paths.py`.
- **Existing tests:** `tests/test_code_review.py`, `tests/test_config_cli.py`, `run_tests.sh`, `tools/specs/validate_state.py`.
- **Source updates:** Scope any future changes to this task; reconcile existing modules and test names with a fresh checkout before implementation. The historical source plan below may name old façades such as `apatch_lib/model.py`; project YAML validation now belongs to `apatch_lib/configuration/loaders.py`.
- **Recovery:** Unverified or stale review evidence must never authorize `CMT` or GitHub operations; retain the current fail-closed, non-destructive behavior.

## Stage-specific implementation details (original advisory plan)


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
