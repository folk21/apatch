# RE-07 Implementation Plan — Review Evidence Acceptance Tests (Advisory)

**Task:** [RE-07](subspec.md#re-07) · **type:** `GEN_TESTS` · **area:** `E2E_TESTS` · **Proposed run type:** `ACCEPT` · **Dependency:** RE-06 documentation sign-off.

## Source inventory and implementation scope

Inspect existing public `api.py` and `contract.md` interfaces, test fixtures and recorded assertions. Treat backend implementation as an independent area: request contract clarification from its owner rather than loading or modifying unrelated private modules. Reconcile exact observable return formats with the current checkout before editing integration tests.

| Test owner (verified snapshot) | Required coverage / source task |
| --- | --- |
| `tests/test_code_review.py` | RE-01 stdout/stderr capture, process limits, review success/failure, integration with CHK and CMT; RE-02/03/05 opt-in orchestration |
| `tests/test_review_normalizer.py` | RE-02 adapters, scanner policy, duplicate keys, nonfinite input, SHA-256 and verdict consistency |
| `tests/test_review_context.py` | RE-03 bounded and consent-gated compact context, deterministic prioritization and omissions |
| `tests/test_review_evidence_api.py` | RE-04 finding lookup, private no-follow source reads, quotas and snapshot integrity |
| `tests/test_review_retention.py` | RE-05 count/age/size eviction, protected entries, locks, prune journal and consent-based export |
| `tests/test_config_cli.py` | RE-01/02/03/05 invalid project policy, defaults and backwards compatibility |
| `tests/test_spec_state.py` | RE-06/07 task ordering, type metadata, selected checkpoint and plan pairing |

Do not assume existing tests already cover every edge case. Map normative IDs to specific methods and inspect their assertions. The table is a verification inventory, not blanket authorization to edit each test file: BACKEND-owned unit tests must be updated by a reopened BACKEND task; this E2E_TESTS task edits only its integration/acceptance test cases and harness. Add new cases only when evidence is missing, using RE-01…RE-05 as the oracle.

## Test skeletons (illustrative only; write real tests in test owners)

Each skeleton is a **design sketch**, not a skipped test or assertion of coverage. Comments are English-only; replace all steps with executable assertions and fixtures during RE-07.

```python
# tests/test_code_review.py
# test_capture_enforces_combined_provider_limit
# Arrange an isolated review directory and a provider emitting bounded stdout and stderr.
# Act by running REV with a provider output that exceeds the combined byte limit.
# Assert that the process stops, private partial evidence persists, and REV does not PASS.

# test_review_rejects_worktree_mutation_and_stale_check
# Arrange a successful CHK snapshot, then mutate a tracked file in a fake reviewer.
# Assert that REV fails closed without accepting the provider verdict.
```

```python
# tests/test_review_normalizer.py
# test_required_scanner_missing_is_not_empty_pass
# Arrange a structured report with a missing required scanner and wrapper exit zero.
# Assert an ESCALATE verdict, preserved provenance, and no fabricated zero findings.

# test_normalizer_rejects_duplicate_keys_and_digest_drift
# Corrupt the JSON or its exact captured-stdout digest independently.
# Assert stable refusal without reading unrelated files or contacting a provider.
```

```python
# tests/test_review_context.py
# test_context_requires_explicit_source_disclosure_consent
# Arrange verified normalized findings and a source diff with identifiable text.
# Assert metadata-only defaults and exact opt-in before any source text appears.

# test_context_prioritizes_high_findings_within_budget
# Fill a bounded context budget using multiple severities.
# Assert deterministic ordering and explicit omission counts; never silently drop high severity.
```

```python
# tests/test_review_evidence_api.py
# test_retrieval_rejects_symlink_path_and_changed_source
# Create private evidence and a nested source path in a temporary Git repository.
# Replace one path component with a symlink or change the source during reading.
# Assert REVIEW_EVIDENCE_UNKNOWN without disclosing source or changing Git state.

# test_retrieval_enforces_request_and_response_budgets
# Request repeated findings with small per-call and total budgets.
# Assert quota consumption, bounded deterministic output, and no partial lines.
```

```python
# tests/test_review_retention.py
# test_prune_interruption_resumes_only_verified_members
# Arrange valid and protected run directories with a simulated unlink interruption.
# Assert a private deletion journal and resumption only after revalidation.

# test_export_is_explicitly_consented_and_metadata_only
# Arrange sensitive raw findings and a completed manifest.
# Assert denied export by default and no source, prompt, message or finding text in export.
```

## Ordered execution

1. Read all five normative task acceptance sections; create a checklist mapping `RE-01-A` through `RE-05-D` to exact existing test methods. Mark missing verification and non-automatable cases; do not invent observed PASS.
2. Add missing integration/E2E positive/negative tests for uncovered behavior using the existing fixtures (`tests/_support.py`) and local temporary Git remotes. Explicitly test legacy default-off compatibility and mode/phase guards.
3. Run affected review suites first; return backend defects or missing focused unit regression tests to the owning BACKEND task; this E2E_TESTS task must not write backend code. Never weaken expected errors to make a test green.
4. Execute `python3 tools/specs/validate_state.py`, `sh ./run_tests.sh` and `sh ./run_rare_checks.sh` as supported. Capture return codes and a bounded failure summary; do not persist raw reviewer output or secrets in ordinary logs.
5. Run the target project's configured canonical `CHK` on the final intended revision. If `REV` is required, run it after fresh CHK, before commit. Confirm source/commit tree evidence and active publication policy; the developer separately authorizes any PSH/PR/MRG/SYN actions.
6. Deliver the test matrix and exact results. Update the current task state only on developer instruction; submission, green tests or merge are not automatic sub-spec acceptance.

## Failure and recovery

- **Missing tool, CI or platform:** report NOT_RUN, do not convert it to PASS; keep final merge blocked under the configured gate.
- **Timeout or killed process:** preserve private diagnostic artifacts and rerun only with explicit, bounded retry rules; never restart a paid provider from a guessed outcome.
- **Changed Git/index/HEAD after CHK:** invalidate verification and repeat canonical checks before publication.
- **Incomplete retention cleanup or corrupted evidence:** fail closed, use the existing audited prune journal and recovery path; do not delete unknown directories.
- **GitHub PR/merge uncertainty:** perform read-only reconciliation, not a blind mutation retry.

## Acceptance

Every normative RE-01…RE-05 contract has evidence or an explicit unresolved blocker; new and updated tests are deterministic and isolated; the configured final CHK is visibly successful on the exact accepted revision; no safety gate has been relaxed.