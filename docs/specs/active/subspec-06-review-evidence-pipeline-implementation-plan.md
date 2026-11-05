# APATCH-PLAN-006 — Review Evidence Pipeline Implementation Plan

**Status:** ADVISORY / DRAFT. **Normative owner:** [APATCH-SUB-006](subspecs/subspec-06-review-evidence-pipeline.md). **Parent:** [APATCH-SPEC-001](spec-apatch-orchestrator.md).

**Current focus:** RE-05 candidate implementation pending developer acceptance. The 2026-11-05 10:02 UTC `apatch_files.txt` is a clean `main` snapshot at `12dc5df7536b6861963118f44b3bd2f20ca12fb9`: 141 file bodies of 145 tracked files. Omitted contents: `apatch.conf`, `.apatch/config.yaml`, `apatch`, `.DS_Store`. Snapshot provenance is not a complete checked-out Git repository; tests that need `apatch.conf` use a local substitute. RE-01–RE-04 remain unaccepted candidates; SUB-003 FS-06 and SUB-004 WM-04 remain ON_HOLD.

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

## RE-03 — Bounded LLM context (candidate implementation)

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

## RE-04 — Read-only selective evidence lookup (candidate implementation)

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

## RE-05 — Retention, export and recovery (candidate implementation)

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

## Stage order / sign-off

`RE-01 -> RE-02 -> RE-03 -> RE-04 -> RE-05`. Do not claim any later stage complete from RE-01 tests. Before moving the selected checkpoint, record review evidence and obtain developer direction. Archive SUB-006 with its entire plan only after all scoped stages are accepted, then reconcile index, umbrella and checkpoint. Existing SUB-003 / SUB-004 acceptance is independent.


