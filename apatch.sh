#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "${1:-}" = "force" ]; then
    shift
    set -- --force "$@"
elif [ "${2:-}" = "force" ]; then
    set -- "$1" --force
fi
if [ "$#" -eq 0 ] || { [ "$#" -eq 1 ] && [ "$1" = "--force" ]; }; then
    PROJECT_ROOT=$(pwd -P)
    PROJECT_NAME=${PROJECT_ROOT##*/}
    set -- "$HOME/Downloads/${PROJECT_NAME}_patch_params.json" "$@"
fi
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/apatch.py" "$@"
