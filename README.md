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

To recover after manually creating a feature branch, extracting a patch, committing, or pushing, use the explicit FORCE mode:

```bash
# Use the default handoff in ~/Downloads/patch_params.json.
/path/to/apatch/apatch.sh force

# Use a specific handoff file.
/path/to/apatch/apatch.sh /path/to/change_params.json force

# The standard long option is also accepted.
/path/to/apatch/apatch.sh --force /path/to/change_params.json
```

FORCE displays all menu actions without phase restrictions and requests explicit confirmation before recovering or changing repository state. A previously created local feature branch can be adopted; an existing clean commit or push can be associated with the handoff; uncommitted worktree changes can be adopted without overwriting them; and Git commits and fast-forward pushes can be made from the checked-out named branch without a previously verified phase. FORCE also supports re-running configured checks and recovering PR/merge state from GitHub. Every state reconciliation is recorded in the project's state file and audit log.

FORCE is **not** a Git `--force` push. It never rewrites remote history, overwrites a dirty worktree with ZIP contents, allows a detached-HEAD patch application, skips ZIP path/digest validation, or bypasses GitHub mergeability, review, or CI requirements. When associating existing files or commits whose contents differ from the ZIP, the tool warns about a manual override and requires confirmation. This mode should be used deliberately: it can intentionally associate manually edited files or commits with a handoff that no longer precisely describes their contents. Use ordinary mode whenever possible.

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

### Starting another patch before the previous cycle finishes

Each ZIP filename has a separate workflow checkpoint. If a newly selected ZIP differs from an unfinished patch for the same repository, `apatch` lists the previous checkpoints and asks whether to start a separate cycle. Declining leaves all checkpoints unchanged; accepting marks the older records as superseded by the new ZIP while preserving their original phases and data for inspection or later recovery. The new cycle has its own state record when its first action saves progress. Applied-patch history is not reset. A dirty working tree is never automatically discarded or overwritten when starting another cycle, even in FORCE mode.

## Configuration

`apatch.conf` is located beside `apatch.py`. Its `[apatch]` section controls:

| Setting | Purpose |
| --- | --- |
| `downloads_dir` | Directory containing change archives. |
| `state_file` | Filename for workflow progress under the target repository's `.apatch/` directory. |
| `applied_patches_file` | Filename for applied-patch history under the target repository's `.apatch/` directory. |
| `log_directory` | Relative path below the target repository's `.apatch/` directory; defaults to `logs`. |
| `remote` | Git remote used for validation and publishing. |
| `base_branch` | Target branch for feature creation and pull requests. |
| `require_patch_feature_branch` | When `true`, restrict direct patch application (option 3) to the `feature_branch` from the handoff file. Defaults to `false`. |
| `require_review_approval` | Require approved review before merging. |
| `require_required_checks` | Require successful GitHub checks before merging. |
| `merge_method` | GitHub merge strategy: `merge`, `squash`, or `rebase`. |
| `max_uncompressed_patch_bytes` | Maximum total extracted archive size. |

All three runtime settings—`state_file`, `applied_patches_file`, and `log_directory`—are now resolved relative to the target repository's `.apatch/` directory. State and history settings must be plain filenames; the log setting may be a relative subdirectory. Absolute paths, `..` traversal, and symlinked destinations are rejected. The global configuration does not define project verification commands.

By default, the runtime files have no repository-name prefix:

- `.apatch/apply_patch.state.json` (and `.apatch/apply_patch.state.json.lock`)
- `.apatch/applied_patches.txt` (and `.apatch/applied_patches.txt.lock`)
- `.apatch/logs/apatch.log`

### Project-specific verification

Each target repository must contain `.apatch/config.yaml` (not a symlink), for example:

```yaml
schema_version: 1
log_directory: logs
checks:
  - ["./gradlew", "test"]
  - ["./gradlew", "check"]
```

`log_directory`, `state_file`, and `applied_patches_file` are optional and override their global counterparts. For example, `log_directory: diagnostics/checks` writes to `<repository>/.apatch/diagnostics/checks/apatch.log`. Separate lock files named `<state_file>.lock` and `<applied_patches_file>.lock` are created automatically in `.apatch/`. Omit these settings to use the generic global names.

`checks` must be a non-empty list. A command can be an argument list (recommended) or a single command string parsed with shell-style quoting:

```yaml
schema_version: 1
checks:
  - ./run_checks.sh
  - ["python3", "-m", "unittest", "discover", "-s", "tests"]
```

Commands run sequentially from the target repository root; execution stops on the first failure. Standard output and standard error from these project checks are displayed live in the terminal, but successful checks do not write their output to the project log. Each command is executed directly **without a shell**, so pipelines, redirections, environment-variable expansion, and `&&` are not interpreted. Put compound shell logic in a project-owned script and call that script from `checks`.

If the project configuration is missing, malformed, or has no commands, `apatch` stops with an explicit error. Adjust the example commands to match each target repository.

## Applied-change history

The file configured by `applied_patches_file` records successful patch applications in blocks separated by a blank line:

```text
Date: 2026-10-22T14:30:00+04:00
Patch: example-service-changes.zip
Planned feature branch: feature/improve-validation
Real feature branch: main
```

`Date` is the local timestamp at initial application (including the UTC offset). The planned feature branch comes from the handoff JSON. The real feature branch initially records the branch on which the patch was applied, including manual FORCE adoption. When `apatch` commits or adopts an existing commit, it updates the real branch to the one containing that commit, preserving the original timestamp. The journal does not claim that a commit exists before the commit step completes.

If the same ZIP filename is encountered again, `apatch` warns and asks for an explicit `yes/no` decision before making changes. For combined branch creation and extraction, this question appears before the branch is created.

This history is independent of saved workflow progress. It detects duplicate **filenames**, not identical archive contents, and does not bypass Git or archive safety checks. Writes use a stable advisory lock and atomic file replacement. Older journals containing one ZIP filename per line remain readable; an entry is upgraded to the structured format if a corresponding commit is subsequently adopted.

### Migration from older installations

Earlier versions used repository-prefixed filenames (such as `example-service_apply_patch.state.json` and `example-service_applied_patches.txt`) inside `.apatch/`, or stored files beside the installed `apatch` tool. When the generic project-local state file is absent, the new version checks those legacy locations and imports only workflow records whose stored repository path matches the current repository. If the generic journal is absent, existing patch history is imported without losing entry metadata. Old files are preserved as backups and never deleted automatically; new lock files are created instead of copying obsolete ones.

If a project already has its generic `.apatch` state or history file, it takes precedence and is never overwritten by legacy data. Remove old `state_file` and `applied_patches_file` overrides from `.apatch/config.yaml` to opt into the generic names; explicitly configured names remain authoritative. When migrating from a previously shared history, review the imported filenames; old journals do not distinguish projects.

## Logging

`apatch` uses Python's standard `logging` module and writes an append-only log to `<repository>/.apatch/<log_directory>/apatch.log`. Every entry includes a timestamp and the change archive's filename as its operation identifier, along with the repository, feature branch, severity, and relevant event details.

Command records include the executable and arguments, working directory, and (for non-check commands) exit status and duration. The complete commit message is recorded **only when the commit command runs**. For canonical checks, the log records command starts and failures only: a failed check records its exit status, duration, and at most the last 20 lines of combined output (up to 500 characters per line). Successful check output is shown live in the terminal but is not written to the log. Output from Git and GitHub commands and other standard input is not retained. Common sensitive arguments are masked. The log file is restricted to the current user (mode `0600`); nevertheless, failure diagnostics and commit messages may contain secrets and should not be shared without review.

To keep runtime files out of patches and commits, `apatch` checks the repository's ignore rules and, when needed, adds precise entries for the log directory, state file, lock file, and applied-patch history to that repository's local `.git/info/exclude`. This does not modify tracked `.gitignore` files and does not affect other repositories. The `.apatch/config.yaml` file itself should be committed as part of the project's normal configuration before starting a patch workflow.

## Safety and recovery

`apatch` checks actual Git and GitHub state before important actions; its saved progress is not treated as authorization or proof of approval. It stops on an unexpected working-tree change, source or remote drift, unsafe archive content, conflicting branch, ambiguous pull request, or failed verification.

Branch creation, committing, publishing, and merging require deliberate user actions. The tool does not force-push, bypass required checks, approve pull requests, or perform an unguarded direct merge. A partial extraction must be inspected before continuing; do not repeat extraction over an unexpectedly modified working tree.
