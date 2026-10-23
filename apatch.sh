#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "${1:-}" = "force" ] || [ "${1:-}" = "loose" ] || [ "${1:-}" = "strict" ]; then
    MODE=$1
    shift
    set -- "--$MODE" "$@"
elif [ "${2:-}" = "force" ] || [ "${2:-}" = "loose" ] || [ "${2:-}" = "strict" ]; then
    HANDOFF=$1
    MODE=$2
    shift 2
    set -- "$HANDOFF" "--$MODE" "$@"
fi
if [ "$#" -eq 0 ] || { [ "$#" -eq 1 ] && { [ "$1" = "--force" ] || [ "$1" = "--loose" ] || [ "$1" = "--strict" ]; }; }; then
    PROJECT_ROOT=$(pwd -P)
    PROJECT_NAME=${PROJECT_ROOT##*/}
    set -- "$HOME/Downloads/${PROJECT_NAME}_patch_params.json" "$@"
fi
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/apatch.py" "$@"
