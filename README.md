# apatch

`apatch` automates and orchestrates repository changes, validation, commits, publishing, pull requests, and merges through an interactive, state-aware workflow.

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

## Run

Start `apatch` **from the root of the project repository** whose development workflow you want to manage:

```bash
/path/to/apatch/apatch.sh /path/to/change_params.json
```

The argument is a JSON file describing the intended change. Global configuration is read from `apatch.conf` next to `apatch.py`; project verification commands and optional log directory overrides are read from the target repository's `.apatch/config.yaml`. The tool presents the actions currently available, validates the repository state before each operation, and records progress so the workflow can resume on a later invocation.

## Change description

The JSON file identifies the target repository, feature branch, archive containing project changes, and commit message. For example:

```json
{
  "schema_version": 1,
  "repository": "example-service",
  "feature_branch": "feature/improve-validation",
  "patch_file": "example-service-changes.zip",
  "commit_message": "refactor: improve validation\n\nSeparate validation responsibilities and retain existing behavior."
}
```

Required fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Supported input format version (`1`). |
| `repository` | Exact directory name of the target repository. |
| `feature_branch` | Feature branch to create or continue (`feature/...`). |
| `patch_file` | Filename **only** of the ZIP archive containing project changes. |
| `commit_message` | Complete Git commit subject and body. |

Optional fields:

| Field | Meaning |
| --- | --- |
| `base_commit` | Expected Git commit before changes are applied. |
| `patch_sha256` | SHA-256 digest of the archive for integrity verification. |
| `delete_paths` | Repository-relative paths of tracked files to remove. |

The archive is located using `downloads_dir` from `apatch.conf`. Its entries must be regular files inside one top-level directory whose name matches `repository`. Git metadata, unsafe paths, and unexpected entries are rejected. Keep `base_commit` and `patch_sha256` whenever these values are known.

## Workflow

The interactive menu supports the following operations, subject to current Git state and saved progress:

1. **Create a feature branch.** Start from a clean, synchronized target branch; refuse creation if the named feature branch already exists locally or on the configured remote.
2. **Create a branch and apply changes.** Perform the branch checks and extract the change archive as one guarded operation.
3. **Apply changes to the current branch.** By default, the checked-out branch may be any named branch, including `main`. The menu displays its name. Check the baseline, archive contents, and clean working tree before modifying files. Automated commit/push and PR operations remain limited to the configured feature branch.
4. **Run project checks.** Execute the configured verification commands and associate a successful result with the exact working-tree content.
5. **Commit and push.** Stage the intended changed, added, and removed files; commit using the provided message; push only when repository and remote-branch checks pass.
6. **Create a pull request.** Find or create a GitHub pull request from the feature branch to the configured target branch. Review and CI remain separate from this action.
7. **Merge and synchronize.** Verify the pull request, approvals, CI, and remote commit identity; merge through `gh`; then switch to the target branch and synchronize with a fast-forward-only pull.

An interrupted push can be retried without creating a second commit. If the remote merge succeeds but local synchronization fails, synchronization can be resumed separately.

## Configuration

`apatch.conf` is located beside `apatch.py`. Its `[apatch]` section controls:

| Setting | Purpose |
| --- | --- |
| `downloads_dir` | Directory containing change archives. |
| `state_file` | External file storing workflow progress. |
| `applied_patches_file` | File recording previously applied archive filenames. |
| `log_directory` | Relative path below the target repository's `.apatch/` directory; defaults to `logs`. |
| `remote` | Git remote used for validation and publishing. |
| `base_branch` | Target branch for feature creation and pull requests. |
| `require_patch_feature_branch` | When `true`, restrict direct patch application (option 3) to the `feature_branch` from the handoff file. Defaults to `false`. |
| `require_review_approval` | Require approved review before merging. |
| `require_required_checks` | Require successful GitHub checks before merging. |
| `merge_method` | GitHub merge strategy: `merge`, `squash`, or `rebase`. |
| `max_uncompressed_patch_bytes` | Maximum total extracted archive size. |

Relative paths for state and history are resolved from the installed `apatch` directory. Unlike them, `log_directory` is always relative to the target repository's `.apatch/` directory. Absolute paths, `..` traversal, and symlinked log directories are rejected. The global configuration does not define project verification commands.

### Project-specific verification

Each target repository must contain `.apatch/config.yaml` (not a symlink), for example:

```yaml
schema_version: 1
log_directory: logs
checks:
  - ["./gradlew", "test"]
  - ["./gradlew", "check"]
```

`log_directory` is optional and overrides the global `log_directory` setting. For example, `log_directory: diagnostics/checks` writes to `<repository>/.apatch/diagnostics/checks/apatch.log`. Omit it to use the global relative setting (`logs` by default).

`checks` must be a non-empty list. A command can be an argument list (recommended) or a single command string parsed with shell-style quoting:

```yaml
schema_version: 1
checks:
  - ./run_checks.sh
  - ["python3", "-m", "unittest", "discover", "-s", "tests"]
```

Commands run sequentially from the target repository root; execution stops on the first failure. Standard output and standard error from these project checks are displayed live and appended to the project log. Each command is executed directly **without a shell**, so pipelines, redirections, environment-variable expansion, and `&&` are not interpreted. Put compound shell logic in a project-owned script and call that script from `checks`.

If the project configuration is missing, malformed, or has no commands, `apatch` stops with an explicit error. The supplied SignalHarvester `.apatch` archive is a starting configuration; verify that its command exists in your SignalHarvester checkout.

## Applied-change history

The file configured by `applied_patches_file` records one successfully applied archive filename per line. If the same filename is encountered again, `apatch` warns and asks for an explicit `yes/no` decision before making changes. For combined branch creation and extraction, this question appears before the branch is created.

This history is independent of saved workflow progress. It detects duplicate **filenames**, not identical archive contents, and does not bypass Git or archive safety checks. Writes are locked and synchronized to disk.

## Logging

`apatch` uses Python's standard `logging` module and writes an append-only log to `<repository>/.apatch/<log_directory>/apatch.log`. Every entry includes a timestamp and the change archive's filename as its operation identifier, along with the repository, feature branch, severity, and relevant event details.

Command records include the executable and arguments, working directory, exit status, and duration. The complete commit message is recorded **only when the commit command runs**. Output from canonical project checks is displayed live and retained in the log; output from Git and GitHub commands and other standard input is not retained. Common sensitive arguments are masked. The log file is restricted to the current user (mode `0600`); nevertheless, project-check output and commit messages may contain secrets and should not be shared without review.

To keep runtime logs out of patches and commits, `apatch` checks the repository's ignore rules and, when needed, adds the precise log-directory path to that repository's local `.git/info/exclude`. This does not modify tracked `.gitignore` files and does not affect other repositories. The `.apatch/config.yaml` file itself should be committed as part of the project's normal configuration before starting a patch workflow.

## Safety and recovery

`apatch` checks actual Git and GitHub state before important actions; its saved progress is not treated as authorization or proof of approval. It stops on an unexpected working-tree change, source or remote drift, unsafe archive content, conflicting branch, ambiguous pull request, or failed verification.

Branch creation, committing, publishing, and merging require deliberate user actions. The tool does not force-push, bypass required checks, approve pull requests, or perform an unguarded direct merge. A partial extraction must be inspected before continuing; do not repeat extraction over an unexpectedly modified working tree.
