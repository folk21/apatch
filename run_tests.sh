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
        exec "$TEST_PYTHON" -B -m tests.timeout_runner -v \
            tests.test_spec_state \
            tests.test_review_normalizer \
            tests.test_code_review.CodeReviewTests.test_structured_review_persists_normalized_report_and_blocks_high_findings \
            tests.test_code_review.CodeReviewTests.test_structured_missing_required_scanner_escalates_and_advisory_missing_warns \
            tests.test_code_review.CodeReviewTests.test_structured_zero_findings_allows_required_review_to_commit \
            tests.test_code_review.CodeReviewTests.test_structured_report_requires_capture_and_configured_scanner_policy \
            tests.test_architecture_characterization \
            tests.test_explicit_action_results \
            tests.test_cli_boundaries \
            tests.test_action_applicability \
            tests.test_audit_rules \
            tests.test_runner_scripts \
            tests.test_timeout_reporting \
            tests.test_validation \
            tests.test_feature_sessions.SessionStateTests \
            tests.test_context.ContextTests.test_new_base_is_local_candidate_not_unverified_remote_authorization \
            tests.test_context.ContextTests.test_missing_check_executable_detected_before_running_any_check \
            tests.test_session_continuation.SessionContinuationTests.test_modified_collision_blocks_before_history_or_source_writes \
            tests.test_guarded_commit.GuardedCommitTests.test_guarded_check_and_commit_exact_patch_scope \
            tests.test_guarded_commit.GuardedCommitTests.test_unknown_staged_path_blocks_even_with_skip_approves \
            tests.test_planner.PlannerTests.test_preview_is_read_only_on_new_zip \
            tests.test_planner.PlannerTests.test_goal_checked_stops_without_commit_or_remote_publication \
            tests.test_publication_goals.PublicationGoalTests.test_stale_pr_head_blocks_merge_before_mutation \
            tests.test_publication_goals.PublicationGoalTests.test_unknown_pr_creation_adopts_exact_open_pr_without_recreating \
            tests.test_macros.LocalMacroTests.test_direct_chk_does_not_execute_macro_prepare_commands \
            tests.test_macros.LocalMacroTests.test_apply_patch_check_verifies_without_committing \
            tests.test_macros.LocalMacroTests.test_prepare_runs_once_before_staging \
            tests.test_macros.LocalMacroTests.test_untracked_output_stops_without_deleting_files \
            tests.test_macros.LocalMacroTests.test_symlink_replacement_requires_manual_review \
            tests.test_macros.LocalMacroTests.test_recheck_once_rejects_continual_mutation \
            tests.test_macros.LocalMacroTests.test_final_status_failure_does_not_mask_original_macro_error \
            tests.test_remote_macros.RemoteMacroTests.test_run_all_new_zip_completes_and_repeated_call_does_not_mutate \
            tests.test_formatting.FormattingTests.test_formatting_runs_before_read_only_checks_and_keeps_index \
            tests.test_formatting.FormattingTests.test_direct_chk_does_not_run_format_commands \
            tests.test_formatting.FormattingTests.test_index_mutation_is_reported_and_preserved \
            tests.test_formatting.FormattingTests.test_symlink_replacement_is_reported_and_preserved \
            tests.test_formatting.FormattingTests.test_formatter_drift_of_project_policy_blocks_remaining_commands \
            tests.test_artifact_preflight.ArtifactPreflightTests.test_read_only_preflight_captures_exact_source_evidence \
            tests.test_artifact_preflight.ArtifactPreflightTests.test_preparation_runs_only_when_explicitly_requested \
            tests.test_artifact_preflight.ArtifactPreflightTests.test_canonical_check_that_changes_source_is_rejected \
            tests.test_artifact_preflight.ArtifactPreflightTests.test_timeout_fails_without_marking_source_as_verified \
            tests.test_artifact_packaging.ArtifactPackagingTests.test_packaging_embeds_exact_source_and_valid_handoff \
            tests.test_artifact_packaging.ArtifactPackagingTests.test_discovery_lists_candidates_without_writing_anything \
            tests.test_artifact_packaging.ArtifactPackagingTests.test_failed_check_never_produces_zip \
            tests.test_artifact_packaging.ArtifactPackagingTests.test_changes_between_preflight_and_packaging_are_blocked \
            tests.test_artifact_packaging.ArtifactPackagingTests.test_undeclared_changes_cannot_be_omitted \
            tests.test_artifact_packaging.ArtifactPackagingTests.test_existing_output_refused_without_overwriting \
            tests.test_help_reference \
            tests.test_code_review.CodeReviewTests.test_required_review_blocks_commit_until_passed \
            tests.test_code_review.CodeReviewTests.test_opt_in_capture_keeps_complete_script_stdout_stderr_and_private_manifest \
            tests.test_code_review.CodeReviewTests.test_capture_exceeding_output_cap_fails_closed_and_marks_truncation \
            tests.test_code_review.CodeReviewTests.test_symlinked_review_storage_is_rejected_before_provider_runs \
            tests.test_code_review.CodeReviewTests.test_model_response_must_have_unambiguous_verdict \
            tests.test_code_review.CodeReviewTests.test_review_script_that_changes_worktree_fails_closed \
            tests.test_code_review.CodeReviewTests.test_guarded_committed_goal_executes_review_before_commit \
            tests.test_zip_resume.ExplicitZipResumeTests.test_apl_and_brn_prefix_are_satisfied_without_replaying_archive \
            tests.test_cache_recovery \
            tests.test_branch_reassignment.PendingZipBranchReassignmentTests.test_reassign_existing_planned_branch_and_resume_fmt_chk \
            tests.test_branch_reassignment.PendingZipBranchReassignmentTests.test_target_local_or_remote_collision_does_not_mutate_checkpoint \
            tests.test_branch_reassignment.PendingZipBranchReassignmentTests.test_goal_checked_can_continue_on_reassigned_branch \
            tests.test_zip_resume.ExplicitZipResumeTests.test_symlinked_cache_refuses_reselection_without_touching_target \
            tests.test_operation_journal.OperationJournalStorageTests.test_invalid_v2_fails_without_overwriting_bytes \
            tests.test_operation_journal.OperationJournalCliTests.test_failed_action_still_creates_run_with_bounded_error \
            tests.test_progress.ProgressStorageTests.test_corrupted_master_is_never_replaced \
            tests.test_safety.SafetyTests.test_canonical_check_timeout_stops_batch_and_preserves_commit \
            tests.test_handoffs.HandoffsTests.test_self_contained_lifecycle_loose \
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
