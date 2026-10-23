# Installation

This guide covers installing the `apatch` CLI and preparing a **target Git repository**. The CLI itself and the repository it operates on are distinct.

## Requirements

- Python 3.10 or newer.
- PyYAML (`python3 -m pip install -r requirements.txt`).
- `git` for repository operations.
- GitHub CLI (`gh`), installed and authenticated, for pull-request operations.
- A target Git repository with a configured remote and `.apatch/config.yaml` specifying its verification commands.

## Get apatch

Download the `apatch` ZIP archive and extract it, or clone the `apatch` Git repository.

Create an isolated Python environment in the extracted `apatch` directory:

```bash
cd /path/to/apatch
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Prepare a target repository

Start `apatch` from the root of the target repository. A configured Git remote and a committed `.apatch/config.yaml` with at least one canonical check are required:

```yaml
schema_version: 1
checks:
  - ["./run_checks.sh"]
```

Replace the example with the repository's actual verification commands. Checks are executed directly without an implicit shell. Do not add `.apatch/` runtime state, journals, locks, backups, or logs to version control; the project-owned `.apatch/config.yaml` is configuration.

The handoff JSON and ZIP are normally placed under `~/Downloads`, subject to `apatch.conf`. When run from a repository root, `apatch.sh` infers `<project>_patch_params.json` if the JSON argument is omitted.

Next: [Usage](USAGE.md) for modes, operations, and handoffs; [Development](DEVELOPMENT.md) for the test suite.
