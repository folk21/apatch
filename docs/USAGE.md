# Usage

This is the user-facing operational reference for `apatch`. Start with [Installation](INSTALLATION.md); use [Architecture](ARCHITECTURE.md) for implementation details and recovery design.

## Run

Start `apatch` **from the root of the project repository** whose development workflow you want to manage:

```bash
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example
```

For a new self-contained patch, the positional identifier is a ZIP stem or basename under `downloads_dir` (`~/Downloads` by default). The ZIP must embed one regular `<repository>/.apatch/params.json` member with the schema-v1 repository name, feature branch, ZIP filename, commit message, and optional base commit or deletions; it must omit its own SHA-256 field. `apatch` verifies the final ZIP hash and saves the validated handoff under the target repository's Git-ignored `.apatch/params.json`. Subsequent invocations can omit the identifier and load this cache. An absent, malformed, unsafe, or wrong-project cache is an error; the tool never guesses the most recent download.

For compatibility, explicit legacy JSON handoffs still work: an unqualified `.json` filename or stem resolves under `downloads_dir` when a matching legacy file exists, and an absolute or relative JSON path is accepted. A ZIP filename ending in `.zip` unambiguously selects embedded ZIP parameters. The P0.3c upgrade itself uses the old ZIP-plus-JSON bootstrap; future handoffs need only the ZIP.

Global configuration is read from `apatch.conf` next to `apatch.py`; project verification commands and optional log directory overrides are read from the target repository's `.apatch/config.yaml`. The tool presents the actions currently available, validates the repository state before each operation, and records progress so the workflow can resume on a later invocation.

**LOOSE is the default execution mode.** Modes can be selected on the command line:

| Mode | Invocation | Behavior |
| --- | --- | --- |
| **LOOSE (default)** | `apatch.sh <zip-stem>` or `apatch.sh` | Allows manual edits, different branches, several patches per commit, and deferred push. |
| **STRICT** | `apatch.sh <zip-stem> strict` or `apatch.sh --strict` | Enforces the expected workflow phase, branch, and verification requirements. |
| **FORCE** | `apatch.sh <zip-stem> force` or `apatch.sh --force` | Reconciles externally performed Git operations, retaining integrity checks. |

### One unfinished feature branch at a time

Before creating any **new** `feature/...` branch with `BRN` (or deprecated legacy `BAP`), `apatch` verifies that no other feature branch is left unfinished. This gate runs in **all three modes**, including FORCE, and **cannot be disabled** through configuration or `skipApproves=true`.

- An open GitHub PR or a remote feature branch that cannot be confirmed merged into the remote base blocks creation with `сначала смерджи fb: <branch>` and identifying details.
- A local-only feature branch with commits not in the local base blocks creation with `Unfinished local feature branch <branch> ...`. Uncommitted changes on the currently checked-out feature branch also block starting a new one.
- An old feature ref retained after its changes were merged does not block a new branch. `apatch` verifies Git ancestry or a matching merged GitHub PR rather than requiring branch deletion.
- If Git remote or GitHub PR status is required but cannot be verified (for example, due to a timeout), creation **fails closed**. Restore connectivity or resolve the old branch, then retry.
- Continuing on an **already existing target feature branch** remains possible under normal mode-specific rules; no new branch is created in that case.

The guard runs before the new Git ref and associated patch changes are created. It checks live Git/PR evidence rather than assuming that a previous apatch checkpoint proves a merge. Ordinary `APL` on an already selected branch does not start a new feature branch and is unaffected.

Use `apatch.sh --help` to see the modes, direct-action selection, and automation parameters. The interactive menu also displays the active mode and the other available modes. Replace `<zip-stem>` in examples with your ZIP filename without `.zip`.

### Several operations in one invocation (`opSeq`)

`opSeq` runs its comma-separated actions in order using the same checks and
guards as individual `op` calls. Numbers and codes can be mixed. In the
new self-contained ZIP workflow, apply first and create the branch second:

```bash
/path/to/apatch/apatch.sh <zip-stem> opSeq=APL,BRN,CHK,CMT,PSH skipApproves=true
/path/to/apatch/apatch.sh <zip-stem> opSeq=3,1,4,5,6 skipApproves=true
```

`skipApproves=true` suppresses confirmation prompts in **every** step, but does
not bypass branch checks, unsafe ZIP checks, CI policies, or GitHub review.
Without the flag, normal confirmations remain required. A failed, interrupted,
or unchanged/cancelled step stops the sequence; earlier successful steps are
not rolled back. The output identifies the last completed step and actions
not executed, so inspect `op=STS` and resume explicitly with `op=` or a
shorter `opSeq`. Never automatically rerun an uncertain remote mutation.

`op` and `opSeq` are mutually exclusive. Reject empty/unknown operations,
`EXT`/`STS` in a sequence, or more than one apply action (`APL`/legacy `BAP`) with
the same handoff. Different ZIPs in one sequence are not yet supported.
Legacy JSON-based sessions retain the old branch-first recovery path.

Outcome lines use `SUCCESS` for an observed state transition, `NO_OP` for an
unchanged action, `CANCELLED` for a declined confirmation, and `ERROR` for a
known operation failure. Supported terminals
show semantic colors; output redirected to a file remains plain text.

### Direct actions and unattended automation

Every menu action can be invoked directly by number or by its mnemonic code (2-4 letters, shown beside the action number in the menu):

```bash
# Apply a patch in the default LOOSE mode; ask for any needed approvals.
/path/to/apatch/apatch.sh <stem> op=3

# Apply a patch without interactive confirmation prompts.
/path/to/apatch/apatch.sh <stem> op=3 skipApproves=true

# Equivalent mnemonic form (case-insensitive; displayed as APL).
/path/to/apatch/apatch.sh <stem> op=APL skipApproves=true

# Move newly applied ZIP changes to the feature branch before verification.
/path/to/apatch/apatch.sh op=BRN skipApproves=true

# Verify, then commit without pushing, then push in separate LOOSE invocations.
/path/to/apatch/apatch.sh op=4 skipApproves=true
/path/to/apatch/apatch.sh op=5 skipApproves=true
/path/to/apatch/apatch.sh op=6 skipApproves=true

# The same sequence using action mnemonics.
/path/to/apatch/apatch.sh op=CHK skipApproves=true
/path/to/apatch/apatch.sh op=CMT skipApproves=true
/path/to/apatch/apatch.sh op=PSH skipApproves=true

# Choose STRICT or FORCE explicitly when necessary.
/path/to/apatch/apatch.sh strict op=4
/path/to/apatch/apatch.sh force op=5 skipApproves=true

# Use an explicit handoff path with automation parameters.
/path/to/apatch/apatch.sh /path/to/change_params.json strict op=4 skipApproves=false

# Inspect the current patch without modifying Git, checkpoints, or history.
/path/to/apatch/apatch.sh op=STS
/path/to/apatch/apatch.sh strict op=10

# Filter stored status by ZIP basename while still selecting the cached handoff.
/path/to/apatch/apatch.sh op=STS patch=example-PATCH-01.zip
```

`op=0` or `op=EXT` exits. Numbers `1`-`9` retain their original operations; `10`/`STS` is the read-only status command. Without `op`, the menu stays interactive and accepts either numbers or codes (for example `APL`). The Python entry point also accepts `--op=3`, `--op=APL`, `--op=STS`, `--skip-approves=true`, `--strict`, `--loose`, and `--force`.

### Current patch status: `10 [STS]`

`STS` reports the patch identity, planned and actual branch, recorded phase, branch creation/reuse provenance (when recorded), application, checks, commit, push, PR, merge, and local-base synchronization. It suggests the next potential operation by its original number and mnemonic. The suggestion is guidance, **not** a bypass of normal action guards.

Each status fact carries an evidence label:

| Label | Meaning |
| --- | --- |
| `VERIFIED` | Confirmed through available, local Git inspection. |
| `RECORDED` | Recorded in the checkpoint, but not independently verified. |
| `UNKNOWN` | Insufficient trustworthy evidence (including missing fields in older states). |
| `CONFLICT` | Available local Git facts contradict the saved checkpoint. |

Status does not contact GitHub or the Git remote by default. A recorded PR number or pushed SHA is not proof of its current remote state. It does not require the original ZIP and does not write to the worktree, Git refs, state file, history, or logs. It reads the cached handoff or an explicit legacy JSON; a missing cache requires an explicit selection. When multiple stored workflows match, `patch=NAME.zip` can narrow the query, but cannot substitute for the handoff selection. Status cannot infer operations performed manually but never checkpointed.

After a successful, state-changing action, the result footer includes a potential next operation. A cancelled or unchanged action reports that no success-path recommendation can be assumed. A failed action stops with a nonzero exit code.

**`skipApproves=false` is the default.** With `skipApproves=false`, direct actions still request their normal confirmations. With `skipApproves=true`, the tool records and auto-approves confirmations, including warnings about a different destination branch, duplicate patches, manual changes, and the current Git remote. It does **not** skip ZIP validation, working-tree checks, backup creation for overlapping edits, remote fast-forward checks, STRICT phase gates, or GitHub review/CI policies. All files selected by a commit action are still staged together. Review the affected paths and repository destination before running unattended actions; there is no automatic rollback of an executed commit or push.

### Console progress and results

The console shows the selected action and its mnemonic, the starting branch and phase, and the number of modified paths. Important Git operations (switching branches, staging, committing, fetching, pushing, and pulling) report completion. Canonical checks stream their output live and end with a success or failure marker.

When an action returns, `apatch` prints a result summary with elapsed time, phase transition, branch, before/after HEAD commit IDs, and the number of changed paths. When appropriate, it lists up to ten changed paths. If an action returns without a detectable transition, the summary explicitly notes that it may have been cancelled or already satisfied. Command failures still stop the action; the script does not claim success for failed operations.

### LOOSE (default): incremental development with manual edits

LOOSE is active automatically and is useful when several patches should accumulate on one branch, when you intend to edit additional files manually, or when committing and pushing should happen at different times:

```bash
/path/to/apatch/apatch.sh <stem> loose
/path/to/apatch/apatch.sh /path/to/change_params.json loose
/path/to/apatch/apatch.sh --loose /path/to/change_params.json
```

LOOSE keeps the Git and ZIP integrity guards but treats workflow drift as a warning. It permits a checked-out branch other than the handoff's suggested branch, an existing dirty worktree, changed files after verification, and a stale handoff `base_commit`. Such mismatches are displayed before the relevant action; commits require explicit confirmation unless `skipApproves=true`. LOOSE never uses `git push --force`.

To combine later patches, apply the first ZIP on the base branch, run `BRN`, and leave the changes uncommitted. Legacy JSON handoffs can still be applied on an existing feature branch using action 3. A new self-contained ZIP must start with `APL` on the base; switching between different embedded handoffs after the initial branch transfer is reserved for the future multi-handoff stage. Existing unrelated edits remain untouched in legacy LOOSE flows. If a legacy archive overlaps with uncommitted changes, `apatch` requests approval and backs up the replaced contents under `.apatch/backups/`.

After the final patch, action 4 runs the project's canonical checks. Git whitespace warnings are reported but do not prevent those checks from running. Action 5 reviews and commits **all** currently changed and staged paths using the active handoff's `commit_message`, without pushing. Check that the message describes the combined change. Action 6 pushes the current branch separately, either now or in a later invocation. Pushes must be fast-forward operations and can only publish committed Git history; any remaining dirty files stay local.

Applied patch history keeps one entry per ZIP. When multiple pending patches on the same branch are committed together, their workflow checkpoints record the same commit SHA and are reconciled together when that commit is pushed. Switching ZIPs in LOOSE preserves earlier checkpoints automatically; nothing is reset or discarded. To apply a new ZIP that intentionally reuses a filename, the duplicate-history warning still requires confirmation unless `skipApproves=true`.

LOOSE, STRICT, and FORCE are mutually exclusive. Prefer the default LOOSE for ongoing development, STRICT for strict phase enforcement, and FORCE for reconciling work already committed or pushed manually.

To recover after manually creating a feature branch, extracting a patch, committing, or pushing, use the explicit FORCE mode:

```bash
# Select the specific handoff by its JSON stem.
/path/to/apatch/apatch.sh <stem> force

# Use a specific handoff file.
/path/to/apatch/apatch.sh /path/to/change_params.json force

# The standard long option is also accepted.
/path/to/apatch/apatch.sh --force /path/to/change_params.json
```

FORCE displays all menu actions without phase restrictions and requests explicit confirmation before recovering or changing repository state unless `skipApproves=true`. A previously created local feature branch can be adopted; an existing clean commit or push can be associated with the handoff; uncommitted worktree changes can be adopted without overwriting them; and Git commits and fast-forward pushes can be made from the checked-out named branch without a previously verified phase. FORCE also supports re-running configured checks and recovering PR/merge state from GitHub. Every state reconciliation is recorded in the project's state file and audit log.

FORCE is **not** a Git `--force` push. It never rewrites remote history, overwrites a dirty worktree with ZIP contents, allows a detached-HEAD patch application, skips ZIP path/digest validation, or bypasses GitHub mergeability, review, or CI requirements. When associating existing files or commits whose contents differ from the ZIP, the tool warns about a manual override and requires confirmation unless `skipApproves=true`. This mode should be used deliberately: it can intentionally associate manually edited files or commits with a handoff that no longer precisely describes their contents. Use LOOSE or STRICT whenever possible.

## Change description

The embedded ZIP metadata (or explicit legacy JSON handoff) identifies the target repository, feature branch, archive containing project changes, and commit message. For example:

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
| `patch_sha256` | SHA-256 digest of the archive for integrity verification; permitted in external legacy JSON and the verified local cache, **forbidden inside the ZIP itself**. |
| `delete_paths` | Repository-relative paths of tracked files to remove. |

The archive is located using `downloads_dir` from `apatch.conf`. Its entries must be regular files inside one top-level directory whose name matches `repository`. Git metadata, unsafe paths, and unexpected entries are rejected. Keep `base_commit` and `patch_sha256` whenever these values are known.

## Workflow

The action numbers are consistent across modes, although their behavior and phase requirements differ:

| `op` | Code | Default LOOSE behavior | STRICT / FORCE behavior |
| --- | --- | --- | --- |
| `0` | `EXT` | Exit | Exit |
| `1` | `BRN` | Move new ZIP changes from the base to the planned feature branch. | Same guarded move; legacy JSON workflows retain branch preparation. |
| `2` | `BAP` | **Deprecated** for self-contained ZIPs; retained only for legacy JSON compatibility. | Same restriction. |
| `3` | `APL` | Start a self-contained ZIP on a clean base branch; legacy JSON flows can apply on other named branches. | STRICT and FORCE apply-first flows validate the base branch; legacy adoption remains supported. |
| `4` | `CHK` | Run/re-run configured checks, allowing manual edits. | Run/re-run configured checks, subject to STRICT phase rules. |
| `5` | `CMT` | **Commit accumulated changes without pushing.** | Commit **and push** (STRICT and FORCE). |
| `6` | `PSH` | **Push** committed history on the current branch. | Retry/reconcile a previous push. |
| `7` | `PR` | Create/find a pull request. | Create/find a pull request. |
| `8` | `MRG` | Merge a reviewed pull request. | Merge a reviewed pull request. |
| `9` | `SYN` | Switch to and fast-forward the local base branch; reconcile PR status when GitHub is available. | FORCE: same as LOOSE. STRICT: requires an already confirmed merge. |

STRICT requires the expected phase and Git state for each action. LOOSE allows manually changed files and an alternative branch, but backs up overlapping modifications before applying ZIP replacements. FORCE supports explicit reconciliation of existing Git operations. All modes retain archive integrity checks, safe Git operations, and GitHub review/CI requirements.

An interrupted push can be retried without creating a second commit. If the remote merge succeeds but local synchronization fails, synchronization can be resumed separately.

For action `PR`, `apatch` first queries GitHub for existing pull requests from the current feature branch, including PRs targeting other base branches. It reuses a unique matching open PR when its head matches the pushed commit; an open PR targeting another base branch or an ambiguous PR history blocks creation. A second lookup verifies a newly created PR. The initial discovery uses one `gh pr list` request, not separate requests for matching and alternate bases.

**Historical PRs do not prove that newly pushed commits have been merged.** If a feature branch was used for an earlier merged/closed PR and then advanced, `PR` can create a new PR for its current pushed SHA, while retaining the old PR in GitHub history. A historical PR for the **same** SHA stops duplicate creation; an existing open PR for an **unexpected** SHA also blocks. After creation, only the unique open PR for the intended SHA is recorded, even when other PRs for the same branch exist.

`MRG` requires that the selected PR's `headRefOid` match the current patch's recorded pushed SHA (or an independently verified local feature ref during manual FORCE recovery). It must never treat a historical `MERGED` PR with a different SHA as completion of the current patch. This check applies regardless of `require_review_approval`, `require_required_checks`, mode, and `skipApproves`. The same identity and revision check is repeated before `synced` is recorded. GitHub merge strategies may produce different commits on the base branch; matching the PR's **source revision** is required independently of its eventual merge commit.

**Recovering a false historical `synced` checkpoint:** Retain the feature branch and its unique commits; do not delete or reset anything. When the current commit is published and still missing from the base, check out that existing feature branch and deliberately run `PR` for the same handoff. After verifying/creating an open PR for the current SHA, `apatch` replaces the stale PR association, clears prior local-sync evidence, and returns the workflow to `pr_created`. Review and merge that new PR separately. If GitHub refuses another PR from the same head branch, stop and arrange a separate reviewed recovery branch; do not retry `MRG` on the old PR. Retrying `SYN` on an older `synced` checkpoint will verify the PR revision again and print a warning if its purported merge cannot be confirmed, without silently rewriting the checkpoint.

Every `gh` CLI invocation has a configurable timeout (45 seconds by default). Recognized transient network failures in explicitly read-only GitHub requests (`gh auth status`, `gh repo view`, `gh pr list`, `gh pr view`, and `gh pr checks`) trigger **one** additional bounded attempt after a short console-reported delay. Other failures do not retry. Within one `MRG` operation, `apatch` reuses the already verified repository identity rather than repeating authenticated `gh repo view` calls, and checks the local Git remote before reusing that identity. Each independent invocation starts with fresh GitHub verification.

`gh pr create` and `gh pr merge` are **never automatically retried**: an interrupted request may already have caused a remote change. If PR creation times out or the verification lookup fails, GitHub may already have created the PR even if `apatch` has not persisted the `pr_created` phase. **Re-run `op=PR` when the connection recovers.** The operation searches for an existing PR before attempting creation, preventing an automatic duplicate in that recovery path. After an uncertain merge or a merge performed manually in GitHub, use explicit `MRG` reconciliation or `SYN` in LOOSE/FORCE to confirm the correct merged revision and synchronize the base. A timeout never counts as evidence of creation, review approval, or merge.

In LOOSE and FORCE, `SYN` first verifies that the working tree is clean, switches to the configured local base branch, and updates it from the configured Git remote using fast-forward-only operations. If the local base branch does not exist, it fetches and creates a tracking branch. This Git synchronization does not require GitHub CLI authentication or API availability. After the Git update, the command attempts a single GitHub PR listing to confirm a matching merged PR. If that request fails, the PR remains open, or PR identity differs, `SYN` reports that PR reconciliation is pending and preserves the existing workflow phase. A successful Git update is not proof that the PR was merged. The new `local_base_head` checkpoint records the synchronized local commit, so a later `SYN` can retry reconciliation. A Git fetch/pull failure remains fatal; if the local branch was already switched, the command explicitly reports the incomplete remote update.

STRICT retains its guarded behavior: the workflow must already be in the `merged` phase, and GitHub must confirm the merge before synchronization is accepted. Neither mode converts an unverified PR to `merged` or `synced` merely because a local branch was updated.

### Starting another patch before the previous cycle finishes

Each ZIP filename has a separate workflow checkpoint. If a newly selected ZIP differs from an unfinished patch for the same repository, `apatch` lists the previous checkpoints and asks whether to start a separate cycle. Declining leaves all checkpoints unchanged; accepting marks the older records as superseded by the new ZIP while preserving their original phases and data for inspection or later recovery. The new cycle has its own state record when its first action saves progress. Applied-patch history is not reset. A dirty working tree is never automatically discarded or overwritten when starting another cycle, even in FORCE mode.

In LOOSE mode the new cycle is acknowledged automatically. Pending patches on the current branch may be applied and eventually committed together. Any overlapping dirty files are backed up before replacement and require confirmation unless `skipApproves=true`.

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
| `require_review_approval` | Require an approved PR review before merging; defaults to `true` and may be overridden by the target repository's `.apatch/config.yaml`. |
| `require_required_checks` | Require published, passing GitHub CI checks before merging; defaults to `true` and may be overridden per repository. |
| `merge_method` | GitHub merge strategy: `merge`, `squash`, or `rebase`. |
| `github_timeout_seconds` | Maximum wait for each `gh` CLI call, including PR discovery, creation, and verification; default `45`, allowed `5`–`300`. Does not limit project tests. |
| `max_uncompressed_patch_bytes` | Maximum total extracted archive size. |

All three runtime settings—`state_file`, `applied_patches_file`, and `log_directory`—are now resolved relative to the target repository's `.apatch/` directory. State and history settings must be plain filenames; the log setting may be a relative subdirectory. Absolute paths, `..` traversal, and symlinked destinations are rejected. The global configuration does not define project verification commands.

By default, the runtime files have no repository-name prefix:

- `.apatch/apply_patch.state.json` (and `.apatch/apply_patch.state.json.lock`)
- `.apatch/applied_patches.txt` (and `.apatch/applied_patches.txt.lock`)
- `.apatch/logs/apatch.log`
- `.apatch/backups/` (created only when LOOSE replaces overlapping dirty files)

### Project-specific verification

Each target repository must contain `.apatch/config.yaml` (not a symlink), for example:

```yaml
schema_version: 1
log_directory: logs
checks:
  - ["./gradlew", "test"]
  - ["./gradlew", "check"]
```

`log_directory`, `state_file`, `applied_patches_file`, `require_review_approval`, and `require_required_checks` are optional and override their global counterparts. For example, `log_directory: diagnostics/checks` writes to `<repository>/.apatch/diagnostics/checks/apatch.log`. Separate lock files named `<state_file>.lock` and `<applied_patches_file>.lock` are created automatically in `.apatch/`. Omit these settings to inherit the global defaults.

To allow merging without an approved review **for one repository**, set the following in that repository's `.apatch/config.yaml` alongside the required `schema_version` and `checks` fields:

```yaml
schema_version: 1
require_review_approval: false
require_required_checks: false
checks:
  - ["./run_checks.sh"]
```

Each project override must be a YAML boolean (`true` or `false`); quoted strings, numbers, and `null` are rejected. If omitted, each setting inherits its corresponding value from the installed `apatch.conf` (both default to `true`). Before MRG, `apatch` prints both effective policies and their independent sources (`project` or `global`).

Disabling review approval does **not** disable CI checks. If your repository does not publish any GitHub CI checks, the default CI guard reports `PR has no published checks; refusing to assume CI passed`. Setting `require_required_checks: false` explicitly skips only `apatch`'s GitHub CI gate for that repository; it does not mean checks passed, and it does not skip the project-local `CHK` operation. The two opt-outs never bypass PR identity/head/base checks, mergeability, GitHub branch protection or rulesets, or the separate confirmation controlled by `skipApproves`. If GitHub refuses the merge, the operation fails without recording a successful merge.

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

### Created-patch ordering and ZIP metadata (P0.3a/P0.3b)

To prevent skipping a generated patch, maintain `<repository>/.apatch/created_patches.txt` with one ZIP **basename** per line, in creation order:

```text
patch-A.zip
patch-B.zip
patch-C.zip
```

When this file exists, `BAP` and `APL` in every mode require the selected ZIP to appear exactly once in the list. Every **earlier** listed ZIP must also appear in the applied-patch journal. For example, when only `patch-A.zip` is recorded as applied, `patch-B.zip` may be applied next, but `patch-C.zip` is rejected with an error identifying the missing `patch-B.zip`. Later un-applied entries do not block earlier entries. Neither FORCE nor `skipApproves=true` bypasses ordering validation. The check occurs before any branch switch, new branch creation, ZIP extraction, or superseding of earlier patch checkpoints.

The registry remains optional: projects without it and without incoming registry metadata retain the existing workflow. Invalid basenames, duplicate or blank lines, unreadable UTF-8, and symlinks cause an explicit error. The file is automatically excluded from Git using `.git/info/exclude`; it is never staged as a source change.

Starting with P0.3b, a patch ZIP **may** contain one reserved metadata member at `<repository>/.apatch/created_patches.txt`. This member contains the complete ordered UTF-8 list, including the ZIP being applied, and must preserve all earlier installed entries in exactly the same order. During `BAP` or `APL`, `apatch` validates the incoming list and any existing local prefix before switching branches or extracting source files. Earlier listed patches must already appear in the applied-patch history. After successfully extracting or explicitly adopting the patch, the tool atomically writes the updated list under a separate lock; the metadata member is **never** extracted into the worktree as source content, added to a Git commit, or included in changed-path verification.

An incoming list that drops, modifies, or reorders an installed entry is rejected, without overwriting the local file. Repeated delivery of an identical list does not rewrite the registry. If extraction finishes but the metadata update fails, the applied-patch journal is not advanced; the worktree and checkpoint retain evidence for explicit recovery (typically `FORCE op=APL`). Successful recovery verifies the actual files and installs the pending list without re-extracting the ZIP. Do not delete the journal or registry to bypass ordering checks. A ZIP containing only this metadata and no source changes/deletions is rejected as an empty patch.

Until this P0.3b implementation is installed in the **target project's `apatch` executable**, do not include the reserved member in a ZIP intended for the older extractor. The P0.3b upgrade ZIP itself must therefore use the previous two-file bootstrap format; subsequent ZIPs may use the reserved member. Never invent missing historical entries: request the current list when full ordering provenance is unavailable.

Before any `BRN` or `BAP` branch creation or switch, every execution mode validates the applied-patch history. If a structured record has a misspelled or corrupted field header, the command stops without switching branches, extracting a ZIP, or altering the journal; its error identifies the line and expected field. Inspect the original entry and correct only the confirmed transcription error. Do not delete the journal or bypass this check to resume work. A prior invocation of an older version may already have created the feature branch before noticing a malformed journal; after repairing the record, that existing branch can be reused, or `APL` can continue the recorded `branch_created` workflow.

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

