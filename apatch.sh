#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/apatch.py" "${1:-$HOME/Downloads/signalharvester_patch_params.json}"
