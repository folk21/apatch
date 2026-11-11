#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    TEST_PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    TEST_PYTHON="python3"
fi

cd "$SCRIPT_DIR"

case "${1:-full}" in
    focused)
        exec "$TEST_PYTHON" -B -m tests.timeout_runner -v \
            tests.characterization.char_cli_contracts \
            tests.characterization.char_workflows \
            tests.characterization.char_archive_guards \
            tests.characterization.char_recovery \
            tests.characterization.char_producer_review \
            tests.characterization.char_destination
        ;;
    full)
        sh ./run_rare_checks.sh
        exec "$TEST_PYTHON" -B -m tests.timeout_runner -v \
            tests.characterization.char_cli_contracts \
            tests.characterization.char_workflows \
            tests.characterization.char_archive_guards \
            tests.characterization.char_recovery \
            tests.characterization.char_producer_review \
            tests.characterization.char_destination
        ;;
    *)
        printf '%s\n' "Usage: sh ./run_characterization.sh [focused|full]" >&2
        exit 2
        ;;
esac
