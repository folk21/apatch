# RE-07 — Review Evidence Acceptance Tests (Draft Task)

- **type:** `GEN_TESTS`.
- **Task ID:** `RE-07`.
- **Status:** DRAFT / NOT STARTED; final task for SUB-006; developer acceptance pending.
- **Sub-spec:** [APATCH-SUB-006](subspec.md).
- **Task plan:** [Implementation plan and test skeletons](task_impl_plan_07_review_acceptance_tests.md).
- **Dependencies:** [RE-01–RE-06](impl_plan.md), with the documentation synchronization task immediately before this one.
- **Proposed run type:** `GEN_FINAL` (configuration-driven run profiles are not yet implemented in `apatch`).

## Required outcome

Generate missing acceptance tests and update existing tests so each normative `RE-01-A`–`RE-05-D` requirement has deterministic positive, negative and recovery evidence. This task concludes the sub-spec development cycle, executes the configured canonical `CHK`, reviews failures and prepares truthful acceptance evidence before any permitted merge.

## Normative requirements and acceptance oracles

**RE-07-A — Matrix coverage.** Maintain a requirement-to-test map covering private capture, structured normalization, bounded LLM context, selective local retrieval, and retention/export recovery. Prefer extending existing tests to avoid duplicates; create new tests only for missing behavior. Tests SHALL be real executable assertions, not skipped placeholders or a fabricated PASS report.

**RE-07-B — Safety and isolation.** Use disposable Git repositories and isolated private review storage. GitHub/network and external model interactions SHALL be mocked or explicitly blocked. Cover malformed evidence, symlink/hardlink/traversal attacks, changed bytes, failed or timed-out providers, bounded outputs, and interrupted deletion and retries. No test may modify the developer's active repository, contact a live paid model, or weaken consent/review/CI gates.

**RE-07-C — End-to-end verification.** Run the actual project-defined `CHK` after tests are generated and updated; run focused review tests and the regular and extended suites (`sh ./run_tests.sh`, `sh ./run_rare_checks.sh`) when feasible. Report exact commands, pass/fail/timeout outcomes and macOS/Linux limitations. A failed, partial or unavailable required check SHALL block claiming a verified final revision.

**RE-07-D — Publication preconditions.** For a configured `GEN_FINAL` workflow, `CHK` must be fresh for the exact final worktree/commit tree, and configured `REV`, required GitHub review/CI and merge safety remain in force. Final PR/merge/sync are not authorized merely by selecting this task or naming a run type; they require separate explicit invocation and live guards.

## Non-goals

- No feature expansion beyond RE-01–RE-05 or code changes unrelated to a demonstrated correctness defect.
- No automatic developer acceptance, deployment, forced push or bypass of review requirements.

## Acceptance evidence

A reviewed requirement-to-test matrix, passing canonical check on the final revision (or a recorded blocker), and concise summary of residual manual cases and developer acceptance status. Test skeletons and an implementation sequence are specified in the paired plan; they are not production tests yet.
