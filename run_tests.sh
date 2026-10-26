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
        exec "$TEST_PYTHON" -B -m unittest -v \
            tests.test_runner_scripts \
            tests.test_validation \
            tests.test_audit.AuditTests.test_audit_without_handoff_is_read_only_and_offline \
            tests.test_audit.AuditTests.test_missing_and_out_of_order_patch \
            tests.test_audit.AuditTests.test_v1_state_missing_commit_and_branch_are_reported_without_upgrade \
            tests.test_handoffs.HandoffsTests.test_multi_zip_sequence_combines_patches_and_final_status \
            tests.test_handoffs.HandoffsTests.test_explicit_followup_zip_after_previous_invocation_combines_uncommitted_changes \
            tests.test_handoffs.HandoffsTests.test_followup_refuses_dirty_feature_branch_without_an_applied_predecessor \
            tests.test_handoffs.HandoffsTests.test_repeated_followup_is_rejected_before_overwriting_manual_repairs \
            tests.test_handoffs.HandoffsTests.test_explicit_interactive_reapplication_with_same_path_set_reports_success \
            tests.test_config_cli.ConfigCliTests.test_direct_action_reapply_duplicate_is_blocked_with_skip_approves \
            tests.test_modes.ModesTests.test_force_repeated_adoption_is_successful_with_unchanged_path_set \
            tests.test_handoffs.HandoffsTests.test_self_contained_lifecycle_strict \
            tests.test_handoffs.HandoffsTests.test_self_contained_lifecycle_loose \
            tests.test_safety.SafetyTests.test_untrusted_zip_cannot_change_project_policy_or_runtime_state \
            tests.test_safety.SafetyTests.test_zip_file_directory_prefix_conflict_aborts_before_extraction \
            tests.test_safety.SafetyTests.test_git_fingerprint_includes_executable_bit_and_index_state \
            tests.test_safety.SafetyTests.test_repeated_successful_checks_are_not_reported_as_no_op \
            tests.test_safety.SafetyTests.test_canonical_check_timeout_stops_batch_and_preserves_commit \
            tests.test_status.StatusTests.test_status_uses_unique_stored_workflow_when_cache_is_absent \
            tests.test_history.HistoryTests.test_history_lock_rejects_concurrent_use \
            tests.test_github.GithubGuardTest.test_github_mutating_commands_are_not_retried \
            tests.test_github.GithubGuardTest.test_pending_check_blocks_merge \
            tests.test_github.GithubGuardTest.test_pr_head_drift_blocks_merge \
            tests.test_github.GithubGuardTest.test_pr_create_timeout_can_be_reconciled_on_next_run_without_duplicate \
            tests.test_progress.ProgressStorageTests.test_two_subprocesses_append_without_lost_updates \
            tests.test_progress.ProgressStorageTests.test_master_and_derived_symlinks_are_refused \
            tests.test_progress.ProgressStorageTests.test_corrupted_master_is_never_replaced \
            tests.test_progress.ProgressOverviewTests \
            tests.test_operation_journal \
            tests.test_progress.ProgressCliTests.test_cli_sequence_records_each_attempt_and_identity
        ;;
    full)
        exec "$TEST_PYTHON" -B -m unittest discover -s tests -v
        ;;
    *)
        printf '%s\n' "Usage: sh ./run_tests.sh [regular|quick|full]" >&2
        exit 2
        ;;
esac
