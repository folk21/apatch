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
            tests.test_macros \
            tests.test_remote_macros.RemoteMacroTests.test_run_all_new_zip_completes_and_repeated_call_does_not_mutate \
            tests.test_formatting \
            tests.test_code_review \
            tests.test_zip_resume.ExplicitZipResumeTests.test_apl_and_brn_prefix_are_satisfied_without_replaying_archive \
            tests.test_branch_reassignment \
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
