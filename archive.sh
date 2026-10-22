#!/usr/bin/env bash
set -euo pipefail

# Build a distributable project archive from the current project root.
PROJECT_DIR="apatch"
ARCHIVE_NAME="${PROJECT_DIR}.zip"
PARENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PARENT_DIR"
rm -f "$ARCHIVE_NAME"
zip -r "$ARCHIVE_NAME" "$PROJECT_DIR" \
  -x "*/.git/*" \
     "*/.venv/*" \
     "*/.idea/*" \
     "*/__pycache__/*" \
     "*.zip" \
     "*/.DS_Store" \
     "*/.vscode/*" \
     "*/.idea/*" \
     "*/.pytest_cache/*" \
     "*/.mypy_cache/*" \
     "*/.ruff_cache/*" \
     "*/.coverage" \
     "*/.coverage.*" \
     "*/.hypothesis/*" \
     "*/logs/*" \
     "*/logs/" \
     "*.log" \
     "*.lock" \
     "*.state.json" \
     "*_applied_patches.txt"
