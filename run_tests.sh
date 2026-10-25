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
case "${1:-full}" in
    quick)
        exec "$TEST_PYTHON" -B -m unittest -v \
            tests.test_handoffs.HandoffsTests.test_multi_zip_sequence_combines_patches_and_final_status \
            tests.test_handoffs.HandoffsTests.test_self_contained_lifecycle_strict \
            tests.test_safety.SafetyTests.test_untrusted_zip_cannot_change_project_policy_or_runtime_state \
            tests.test_safety.SafetyTests.test_zip_file_directory_prefix_conflict_aborts_before_extraction \
            tests.test_safety.SafetyTests.test_git_fingerprint_includes_executable_bit_and_index_state \
            tests.test_safety.SafetyTests.test_repeated_successful_checks_are_not_reported_as_no_op \
            tests.test_status.StatusTests.test_status_uses_unique_stored_workflow_when_cache_is_absent \
            tests.test_history.HistoryTests.test_history_lock_rejects_concurrent_use \
            tests.test_github.GithubGuardTest.test_github_mutating_commands_are_not_retried
        ;;
    full)
        exec "$TEST_PYTHON" -B -m unittest discover -s tests -v
        ;;
    *)
        printf '%s\n' "Usage: sh ./run_tests.sh [quick|full]" >&2
        exit 2
        ;;
esac
