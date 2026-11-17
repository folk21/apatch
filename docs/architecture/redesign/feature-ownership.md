# Feature and source ownership traceability (R1 proposal)

**Status:** provisional candidate destinations; current symbols are verified
in the 2026-11-11 snapshot. The repository has *no single discovered runtime
featureID registry* (`featureID` / `feature_id` are absent from inspected
Python source). IDs in this table come from the existing SDD files, not from
newly invented decorator or class metadata. Do not rewrite accepted archived
specifications merely to align an internal Python package layout.

| Existing feature / stage ownership | Verified current symbols and files | Proposed public owner/API | Focused test sources |
| --- | --- | --- | --- |
| SUB-001 / P0 workflow control | `cli_request.CliRequest`, `application.execute_request`, `branch_patch.BranchPatchActions`, `core.actions.ACTION_CODES` | `runtime.api` request interface; `workflows.api` phase/action engine; `handoff.api` ZIP selection | `test_cli_boundaries.py`, `test_handoffs.py`, `test_sequences.py`, `char_cli_contracts.py` |
| SUB-002 / P1.1–P1.2 operation history and audit | `operation_events.OperationRun`, `state.read_state_snapshot`, `audit_rules.reconcile_workflow_records`, `reconciliation.audit_repository` | `workflows.api` state/journal read; `audit.api` read-only reconcile | `test_operation_journal.py`, `test_audit.py`, `test_history.py` |
| SUB-003 / FS-00R, FS-01–FS-06 | `session.FeatureSession`, `context.ContextReport`, `session_continuation.SessionContinuationEvidence`, `planner.build_plan`, `commit_scope.CommitScope`, `zip_resume.verify_applied_zip` | `workflows.api` sessions/goals, `handoff.api` ZIP evidence; Git through `git.api` | `test_feature_sessions.py`, `test_session_continuation.py`, `test_guarded_commit.py`, `test_zip_resume.py`, `char_recovery.py` |
| SUB-004 / WM-01–WM-06 | `progress.ProgressEvent`, `macros.execute_macro`, `formatting`, `loose.LooseActions`, `github.merge_pr`, `github.sync_base` | `audit.api` progress, `workflows.api` macros/checks, `publication.api` merge/sync | `test_progress.py`, `test_macros.py`, `test_remote_macros.py`, `test_formatting.py` |
| SUB-005 / AS-01–AS-07 (accepted) | `core.contracts.ActionResult`, `action_executor.execute_workflow_action`, `audit_collectors.collect_local_evidence`, `cli_request.parse_request` | `workflows.api` result and execution, `audit.api` collectors, `runtime.api` grammar | `test_architecture_characterization.py`, `test_explicit_action_results.py`, `test_audit_rules.py` |
| SUB-006 / RE-01 | `code_review.run_review`, `review_artifacts.ReviewArtifacts` | `review.api.run_review`, provider/evidence adapters | `test_code_review.py`, `test_review_retention.py` |
| SUB-006 / RE-02 | `review_normalizer.normalize_report`, `review_artifacts.ReviewArtifacts.verified_normalized` | `review.api` normalized reports | `test_review_normalizer.py`, `test_code_review.py` |
| SUB-006 / RE-03 | `review_context.build_review_context`, `code_review.run_review` | `review.api` bounded reviewer contexts | `test_review_context.py`, `test_code_review.py` |
| SUB-006 / RE-04 | `review_evidence_api.ReviewEvidenceSession` | `review.api` selective read-only evidence | `test_review_evidence_api.py` |
| SUB-006 / RE-05 | `review_retention.prune_review_artifacts`, `review_retention.export_review_summary` | `review.api` retention/export | `test_review_retention.py`, `test_code_review.py` |
| Producer-side ZIP flows | `artifact_preflight.preflight`, `artifact_packaging.pack_source`, `patch.inspect` | `handoff.api` verification/packaging | `test_artifact_preflight.py`, `test_artifact_packaging.py`, `char_producer_review.py` |

### Traceability rules for implementation

1. Resolve every ID to the *actual* current spec requirement, owning runtime
   public API, owning model/decision symbol and negative/positive tests.
   This table is an ownership index, not a new SDD acceptance declaration.
2. A runtime feature ID MAY be introduced later for diagnostics only after a
   separate data/schema design; no new mandatory persisted field is justified
   by code organization alone.
3. Forbid a feature ID pointing only to a private class. Its first code
   referent must be a public API symbol (or documented compatibility facade),
   then an internal implementation owner and tests.
4. The current `STATE.json` focuses SUB-006 / RE-05. Its `FS-06` and `WM-04`
   checkpoint values are existing state facts, not evidence that those specs
   were accepted or re-scoped by this R1 proposal.
5. Verify this map against a clean current `main` checkout at the start of R2:
   the inspected snapshot was on a dirty characterization branch.

### R2.2 ownership update (behavior-preserving extraction)

The verified source symbols above remain a baseline inventory. After the R2.1
configuration/review model extraction and R2.2 handoff/publication value
extraction, these *implemented* public ownership links supersede the
corresponding **proposed** names for the listed boundaries:

| Existing capability | Implemented owner and public symbol | Transitional historical alias | Contract test |
| --- | --- | --- | --- |
| SUB-001 handoff metadata and SUB-003 ZIP selection | `apatch_lib.handoff.api.Handoff`, `parse_handoff_payload`, `load_handoff`, `safe_relative` | `apatch_lib.model` exports the same objects | `tests.test_domain_model_boundaries`, `tests.test_handoffs` |
| SUB-004 GitHub PR evidence and SUB-002 audit interpretation | `apatch_lib.publication.api.GitHubPr`, `GitHubPrIdentity` | `apatch_lib.core.contracts` exports the same types | `tests.test_domain_model_boundaries`, `tests.test_github` |
| SUB-004 remote publication uncertainty | `apatch_lib.publication.api.RemoteOutcomeUnknown` | `apatch_lib.model.RemoteOutcomeUnknown` is the same exception class | `tests.test_domain_model_boundaries`, `tests.test_explicit_action_results` |

The existing SDD stage identifiers have not changed. Runtime action ownership
remains in the existing adapters; R2.2 changes only type/metadata ownership.
The next migration must address `core.contracts.ActionResult` and workflow
state types without creating an import-name collision with `workflow.py`.

### R2.3 workflow value ownership (behavior-preserving extraction)

| Existing capability | Implemented public owner | Compatibility import | Test |
| --- | --- | --- | --- |
| SUB-001 / P0 action identifiers and phases | `workflows.api.ACTION_CODES`, `action_number`, `WorkflowPhase`, `PHASE_VALUES` | `core.actions`, `core.enums` | `test_workflow_domain_boundaries.py`, `test_sequences.py` |
| SUB-005 / AS-03 completion evidence | `workflows.api.ActionResult`, `OperationOutcome` | `core.contracts.ActionResult`, `core.enums.OperationOutcome` | `test_workflow_domain_boundaries.py`, `test_explicit_action_results.py` |
| SUB-002 / P1 persisted workflow views | `workflows.api.WorkflowRecord`, `StateDocument` | `core.contracts` | `test_workflow_domain_boundaries.py`, `test_operation_journal.py` |
| SUB-004 / WM verification drift | `workflows.api.CheckWorktreeChanged` | `model.CheckWorktreeChanged` | `test_workflow_domain_boundaries.py`, `test_modes.py` |

The plural package name avoids shadowing the legacy `workflow.py` engine.
No SDD ID, checkpoint, action number, or on-disk schema changes in this slice.

### R3.1 Git read-only worktree ownership (behavior-preserving extraction)

| Existing capability | Implemented public owner | Compatibility import | Test |
| --- | --- | --- | --- |
| SUB-001 / P0 worktree inspection before ZIP application | `git.api.inspect_repository`, `inspect_worktree`, `WorktreeSnapshot` | Legacy runner and status observations remain in `gitutil` | `test_git_domain_boundaries.py`, `test_safety.py` |
| SUB-003 / FS-05 scope and SUB-004 / WM-04 verification drift | `git.api.WorktreeEntry`, `worktree_inventory`, `worktree_change_details` | `gitutil.WorktreeEntry`, `worktree_inventory`, `worktree_change_details` are identical aliases | `test_git_domain_boundaries.py`, `test_artifact_preflight.py` |
| Producer-side ZIP verification and packaging | `git.api.current_branch`, `head`, `worktree_fingerprint`, `worktree_inventory` | `gitutil.run` and `output` remain legacy command ports | `test_artifact_packaging.py`, `test_artifact_preflight.py` |

The new read-only snapshot APIs do not grant mutation authority and must be
revalidated by the caller before any write. No feature ID, SDD checkpoint,
ZIP payload, or persistence field changes in R3.1.

### R3.2 subprocess command execution ownership

The existing argv-only runner, bounded canonical-check stdout and failure
summary, redacted logging, and command deadlines are owned by
`apatch_lib.git.commands`. Historical `gitutil.run`, `display_command`,
`command_description`, and `_check_failure_summary` are identical object
exports. `gitutil.output` continues to call its locally patchable `run` name.
No new `git.api` mutation methods, SDD features, state schema, or permissions
are introduced. Safety, timeout and Git boundary regressions remain the
acceptance tests, with `tests/test_git_command_boundaries.py` added for
the new owner.
