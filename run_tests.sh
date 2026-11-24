#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    TEST_PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    TEST_PYTHON="python3"
fi

if ! "$TEST_PYTHON" -c 'import yaml' >/dev/null 2>&1; then
    printf '%s\n' "STOP: PyYAML is missing from the selected Python interpreter: $TEST_PYTHON" >&2
    printf '%s\n' "Set up the apatch virtual environment and install requirements:" >&2
    printf '%s\n' "  cd $SCRIPT_DIR" >&2
    printf '%s\n' "  python3 -m venv .venv" >&2
    printf '%s\n' "  .venv/bin/python -m pip install -r requirements.txt" >&2
    exit 2
fi

cd "$SCRIPT_DIR"
case "${1:-regular}" in
    regular|quick)
        # Keep canonical CHK bounded while retaining critical safety coverage.
        # Exhaustive integration and recovery cases remain in full discovery.
        exec "$TEST_PYTHON" -B -m tests.timeout_runner -v \
            tests.test_spec_state \
            tests.test_document_frontmatter \
            tests.test_feature_traceability \
            tests.test_review_normalizer \
            tests.test_review_context \
            tests.test_review_evidence_api \
            tests.test_review_retention \
            tests.test_code_review.CodeReviewTests.test_structured_review_persists_normalized_report_and_blocks_high_findings \
            tests.test_code_review.CodeReviewTests.test_required_review_blocks_commit_until_passed \
            tests.test_architecture_characterization.GithubBoundaryCharacterizationTests.test_uncertain_remote_mutation_is_not_replayed \
            tests.test_architecture_characterization.GithubBoundaryCharacterizationTests.test_bounded_pr_json_and_malformed_unicode_raise_abort \
            tests.test_configuration_architecture \
            tests.test_domain_model_boundaries \
            tests.test_workflow_domain_boundaries \
            tests.test_git_domain_boundaries.GitDomainBoundaryTests.test_worktree_drift_is_rejected_without_writes \
            tests.test_git_command_boundaries \
            tests.test_explicit_action_results \
            tests.test_cli_boundaries \
            tests.test_action_applicability.ApplicabilityMatrixTests \
            tests.test_audit_rules \
            tests.test_runner_scripts \
            tests.test_module_prefixes \
            tests.test_r1_module_ownership \
            tests.test_r2_cli_presentation \
            tests.test_deploy_apatch.StandaloneDeployTests.test_failed_validation_preserves_current_release \
            tests.test_timeout_reporting.TimeoutReportingTests.test_clean_run_reports_zero_timeouts \
            tests.test_timeout_reporting.TimeoutReportingTests.test_isolated_runner_blocks_unmocked_gh_commands \
            tests.test_validation \
            tests.test_feature_sessions.SessionStateTests \
            tests.test_context.ContextTests.test_missing_check_executable_detected_before_running_any_check \
            tests.test_session_continuation.SessionContinuationTests.test_modified_collision_blocks_before_history_or_source_writes \
            tests.test_guarded_commit.GuardedCommitTests.test_unknown_staged_path_blocks_even_with_skip_approves \
            tests.test_planner.PlannerTests.test_preview_is_read_only_on_new_zip \
            tests.test_macros.LocalMacroTests.test_direct_chk_does_not_execute_macro_prepare_commands \
            tests.test_check_gate.CheckBoundaryTests.test_default_blocks_cmt_and_chk_unblocks \
            tests.test_check_gate.CheckBoundaryTests.test_merge_gate_rechecks_final_head_and_policy_before_github \
            tests.test_check_gate.CheckBoundaryTests.test_unchecked_commit_on_base_is_rejected_even_when_relaxed \
            tests.test_artifact_preflight.ArtifactPreflightTests.test_canonical_check_that_changes_source_is_rejected \
            tests.test_artifact_packaging.ArtifactPackagingTests.test_failed_check_never_produces_zip \
            tests.test_help_reference \
            tests.test_zip_resume.ExplicitZipResumeTests.test_apl_and_brn_prefix_are_satisfied_without_replaying_archive \
            tests.test_handoff_resume_boundaries \
            tests.test_cache_recovery.CacheRecoveryTests.test_tampered_zip_does_not_repair_invalid_cache \
            tests.test_branch_reassignment.UpfrontZipBranchSelectionTests.test_existing_destination_branch_blocks_new_zip_before_extraction \
            tests.test_operation_journal.OperationJournalStorageTests.test_invalid_v2_fails_without_overwriting_bytes \
            tests.test_progress.ProgressStorageTests.test_corrupted_master_is_never_replaced \
            tests.test_safety.SafetyTests.test_canonical_check_timeout_stops_batch_and_preserves_commit \
            tests.test_handoffs.HandoffsTests.test_clean_committed_multi_zip_branch_accepts_explicit_followup \
            tests.test_github.GithubGuardTest.test_pr_head_drift_blocks_merge
        ;;
    full)
        exec "$TEST_PYTHON" -B -m tests.timeout_runner --full
        ;;
    *)
        printf '%s\n' "Usage: sh ./run_tests.sh [regular|quick|full]" >&2
        exit 2
        ;;
esac
