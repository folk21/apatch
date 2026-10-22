#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "${1:-}" = "force" ]; then
    shift
    set -- --force "$@"
elif [ "${2:-}" = "force" ]; then
    set -- "$1" --force
fi
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/apatch.py" "$@"
