---
type: Module Contract
title: Review module contract
description: Review execution, normalized findings, bounded evidence, retrieval, and retention boundaries.
---
# Review module contract

## Ownership and public API

`mo_review` owns review execution, normalized scanner reports, private raw
evidence capture, consent-gated LLM context, selective evidence retrieval,
and protected retention/export. `mo_review.api` retains the effect-free
`ReviewProvider` and `ScannerPolicy` value objects.

Runtime entry points remain explicit implementation modules:
`code_review.run_review`, `code_review.require_fresh_review`,
`review_normalizer.normalize_report`, `review_context.build_review_context`,
`review_evidence_api.ReviewEvidenceSession`, and the opt-in retention/export
operations in `review_retention`. No new CLI action or approval bypass is
introduced by this ownership change.

## Compatibility, security, and recovery

Historical `apatch_lib.code_review` and `apatch_lib.review_*` import paths
resolve to the canonical `mo_review` modules with exact module identity,
including existing test and instrumentation patch targets.

Review output is untrusted. Verified review requires fresh CHK evidence,
provider status, privacy consent, source/index/branch/policy fingerprints,
and bounded no-follow access to stored evidence. With explicit project
`review_allow_without_chk: true`, REV can also run in unchecked diagnostic mode
outside the verified patch phase, including on the base branch. Its result is
marked `mode: unchecked` and never satisfies `review_required` at commit time.
The checked mode and drift refusal are unchanged. Missing or corrupt evidence
fails closed; retention remains opt-in and bounded.

## Verification

Run the focused review tests, `tests.test_code_review`,
`tests.test_review_acceptance`, and the canonical `run_tests.sh` suite.
