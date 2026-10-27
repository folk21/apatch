#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    QUALITY_PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    QUALITY_PYTHON="python3"
fi

if [ "$#" -gt 1 ]; then
    printf '%s\n' "Usage: sh ./run_quality.sh [all|lint|types]" >&2
    exit 2
fi

case "${1:-all}" in
    all|lint|types) MODE="${1:-all}" ;;
    *)
        printf '%s\n' "Usage: sh ./run_quality.sh [all|lint|types]" >&2
        exit 2
        ;;
esac

cd "$SCRIPT_DIR"

if [ "$MODE" = "all" ] || [ "$MODE" = "lint" ]; then
    if ! "$QUALITY_PYTHON" -B -m ruff --version >/dev/null 2>&1; then
        printf '%s\n' "NOT_RUN: Ruff is unavailable; install requirements-quality.txt using $QUALITY_PYTHON" >&2
        exit 2
    fi

    "$QUALITY_PYTHON" -B -m ruff check --no-cache \
        apatch_lib/core apatch_lib/action_applicability.py apatch_lib/audit_rules.py
    "$QUALITY_PYTHON" -B -m ruff format --check --no-cache \
        apatch_lib/core/__init__.py apatch_lib/core/contracts.py apatch_lib/core/enums.py
fi

if [ "$MODE" = "all" ] || [ "$MODE" = "types" ]; then
    if ! "$QUALITY_PYTHON" -B -m mypy --version >/dev/null 2>&1; then
        printf '%s\n' "NOT_RUN: mypy is unavailable; install requirements-quality.txt using $QUALITY_PYTHON" >&2
        exit 2
    fi

    "$QUALITY_PYTHON" -B -m mypy --no-incremental --cache-dir=/dev/null \
        apatch_lib/core/actions.py apatch_lib/core/contracts.py \
        apatch_lib/core/enums.py apatch_lib/core/paths.py \
        apatch_lib/action_applicability.py
fi
