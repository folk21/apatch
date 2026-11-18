# Installation

This guide covers installing the `apatch` CLI and preparing a **target Git repository**. The CLI itself and the repository it operates on are distinct.

## Requirements

- Python 3.10 or newer.
- PyYAML (`python3 -m pip install -r requirements.txt`).
- `git` for repository operations.
- GitHub CLI (`gh`), installed and authenticated, for pull-request operations.
- A target Git repository with a configured remote and `.apatch/config.yaml` specifying its verification commands.

## Recommended: install a separate deployed CLI

Use a versioned deployment when the `apatch` source checkout is also the repository
being patched. The deployed CLI is a copy of committed source, with an isolated
Python environment and a stable launcher; applying a broken patch to the development
checkout does not change the active deployment.

Clone the repository, keep its `main` branch at the intended release commit, and
verify that `HEAD` matches the **local** `origin/main` tracking ref. The deploy tool
does not contact a remote to refresh that ref. Run the installer from the source
checkout, not from a target repository:

```bash
cd /path/to/apatch
python3 tools/deploy_apatch.py install --source .
~/.local/bin/apatch --help
python3 tools/deploy_apatch.py status
```

The installer uses only committed Git files, even if the source worktree contains
uncommitted changes. It creates a Python environment and installs `requirements.txt`,
then runs smoke checks and `sh ./run_tests.sh` **before activation**. A failure leaves
the currently active deployment unchanged. It does not run Git push, PR, or merge.
Use `--smoke-only` only when deliberately accepting a weaker deployment check.

The deployment layout is:

```text
~/.local/bin/apatch                 # Stable executable wrapper
~/.local/bin/apatch.sh              # Equivalent wrapper
~/.local/opt/apatch/current         # Active release pointer
~/.local/opt/apatch/previous        # Previous release pointer
~/.local/opt/apatch/releases/       # One directory per Git commit
~/.local/opt/apatch/apatch.conf     # Persistent global configuration
```

Run `~/.local/bin/apatch` from the **target repository root**. To use the short
`apatch` command, include `~/.local/bin` in your shell's `PATH` and verify the
resolved executable with `command -v apatch`. Update by running `install` again
after merging and synchronizing `main` in the development checkout. To undo an
unsuccessful deployment, stop any running `apatch` processes and run:

```bash
python3 /path/to/apatch/tools/deploy_apatch.py rollback
python3 /path/to/apatch/tools/deploy_apatch.py status
```

### Migrating from a development-checkout installation

**Do not copy** the old source tree, `.venv`, Git directory, cached ZIP handoff,
project state, applied-patch history, locks, backups, or logs into the deployment.
Target-repository state (including `.apatch/config.yaml`, `.apatch/params.json`,
checkpoints, and journals) remains in each target repository and is read by the
new executable without migration. Existing ZIP files remain in the configured
`downloads_dir`; they need not be copied.

The **installation-wide** activity summary is different: the first deployment
copies `<source-checkout>/.apatch/progress/` into the new release, if present.
Updates and rollbacks copy that progress data from the currently active release.
Stop all running `apatch` processes during these operations to avoid losing new
events written concurrently. Do not remove the previous installation until you
have verified the deployed CLI and its `info=PROGRESS` output.

The deployment preserves **global** `apatch.conf` outside its versioned releases.
By default the first installation uses the committed `apatch.conf` from `main`.
If the old installation has a personalized global configuration (for example,
`downloads_dir`, remote, base branch, or timeout settings), explicitly select it
**on the first install**:

```bash
python3 tools/deploy_apatch.py install --source . --config /path/to/old/apatch.conf
```

Future deploys and rollbacks reuse `~/.local/opt/apatch/apatch.conf`; do not edit
a release-local `apatch.conf` or expect uncommitted edits in the source checkout
to be deployed automatically. Inspect and edit the preserved file explicitly
when settings need to change. Keep credentials out of this file.

## Alternative: use an extracted or development checkout directly

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

If the tool directory is already on your `PATH`, use `apatch` directly. ZIP patch application preserves the executable bit of the new launcher. This direct-checkout installation is less resilient to development changes than the recommended separate deployment.

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

