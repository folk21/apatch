---
type: Implementation Guide
title: RE-06 Implementation Plan — Documentation Synchronization (Advisory)
description: Advisory RE-06 implementation plan, dependencies, verification, and recovery steps.
document_role: task_plan
parent: subspec.md
spec_status: draft
plan_status: advisory
task_id: RE-06
task_type: UPD_DOCS
area: DOCS
rtype: DEVELOP
feature_ids:
- REVIEW.RAW_CAPTURE
- REVIEW.NORMALIZATION
- REVIEW.LLM_CONTEXT
- REVIEW.RETRIEVAL
- REVIEW.RETENTION_EXPORT
---
# RE-06 Implementation Plan — Documentation Synchronization (Advisory)

**Task:** [RE-06](subspec.md#re-06) · **type:** `UPD_DOCS` · **area:** `DOCS` · **Prerequisite:** RE-01–RE-05 behavior inspected in the current checkout.

## Source inspection and per-file changes

1. Read the public review/configuration contracts and observed test evidence for actual interfaces and feature gates. Do not load or modify application private implementation as part of the DOCS area. Verify installed `13 [REV]` and configured reviewer behavior; do not infer availability from a spec.
2. `README.md`: retain only a short feature overview and links. Avoid chronological release notes.
3. `docs/USAGE.md`: describe relevant YAML options (`review_artifacts_enabled`, `review_artifact_max_bytes`, `review_retention_*`, `review_context_*`, `review_required`) and explicit `REV`, `CHK`, `CMT` interaction. Link to module contracts for internal retrieval/export APIs; do not present internal functions as CLI commands.
4. `docs/ARCHITECTURE.md`: retain compact ownership, trust/data-flow, manifest integrity, retention lock and interrupted-cleanup recovery descriptions. Include security boundaries in this existing owner; no parallel SECURITY guide.
5. `docs/INSTALLATION.md` and `docs/specs/README.md`: fix relevant navigation links; update only after validating actual destinations. Do not modify `apatch_lib/**/contract.md` here; coordinate such changes with RE-01–RE-05 owners.

## Algorithm and failure handling

- Build a small behavior-to-document table; check each statement against one concrete source or test. If a key, status or API is not verified, mark the statement deferred instead of guessing.
- Collect the relative Markdown links in changed documents and resolve them within the repository, excluding external URLs and intentionally generated paths. A dangling link is a blocking documentation failure.
- Do not alter persisted records or run external reviewers to generate documentation. Preserve any intentional custom project instructions when modifying `AGENTS.md`.

## Verification and acceptance

- Run `python3 tools/specs/validate_state.py`, `python3 -B -m unittest -q tests.test_spec_state` and a link checker on changed documents.
- Run `git diff --check` in the isolated workspace; inspect documentation for claims of accepted/merged stages.
- Hand off the concise document diff and unresolved questions to the developer. If a correctness issue is found in runtime source, open a separate `GEN_CODE` issue rather than silently fixing it under this task.