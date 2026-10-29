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

The executable `apatch` launcher (without `.sh`) is available in the same directory as `apatch.sh`. Both accept identical arguments; the existing `apatch.sh` remains supported. From a target repository root, run:

```bash
/path/to/apatch/apatch <zip-stem> op=APL
```

If the tool directory is already on your `PATH`, use `apatch` directly. ZIP patch application preserves the executable bit of the new launcher.

## Prepare a target repository

Start `apatch` from the root of the target repository. A configured Git remote and a committed `.apatch/config.yaml` with at least one canonical check are required:

```yaml
schema_version: 1
checks:
  - ["./run_checks.sh"]
```

Replace the example with the repository's actual verification commands. Checks are executed directly without an implicit shell. For projects merging into a branch other than the global `main` default, add `base_branch: develop` (or that project's actual target) to the same YAML file. The configured remote must contain the named branch. Do not add `.apatch/` runtime state, journals, locks, backups, or logs to version control; the project-owned `.apatch/config.yaml` is configuration.

Place a self-contained ZIP under `downloads_dir` (`~/Downloads` by default). It must contain exactly one regular `<repository>/.apatch/params.json` metadata member. No separate JSON download is required. Start with `apatch.sh <zip-stem> op=APL`, then use `apatch.sh op=BRN`, followed by checks and publication actions; later invocations read the validated `.apatch/params.json` cache. An explicit legacy JSON handoff remains supported for migration. See [Usage](USAGE.md#several-operations-in-one-invocation-opseq) for one-command sequences and `handoffSeq`.

Next: [Usage](USAGE.md) for modes, operations, and handoffs; [Development](DEVELOPMENT.md) for the test suite.
