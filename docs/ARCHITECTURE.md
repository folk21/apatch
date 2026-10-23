# Architecture

This document describes the implemented components and operational boundaries of `apatch`. It is **descriptive**, not a normative SDD specification. See [Usage](USAGE.md) for user-facing commands, and [Development](DEVELOPMENT.md) for testing and contribution rules.

## Purpose and trust boundaries

`apatch` is an external Python CLI that orchestrates changes in an **existing target Git repository**. The installed `apatch` directory contains code and `apatch.conf`; the current working directory identifies the target Git repository. The two must not be confused.

Inputs include an untrusted handoff JSON, a ZIP patch archive, repository-local `.apatch/config.yaml`, local Git state, and optional GitHub PR state. Relevant boundaries are:

- ZIP members, requested deletions, and configured paths must not escape the target repository or modify Git metadata.
- Manual working-tree changes are user-owned; patch application must avoid silent data loss.
- A handoff describes intended operations; neither it nor persisted workflow state proves that Git or GitHub operations occurred.
- GitHub status, approvals, and remote refs are external facts and may change between calls.
- Runtime diagnostics may reveal source text or credentials, so logging has bounded and redacted content.

## Execution flow

1. `apatch.sh` normalizes supported shell-friendly mode arguments and invokes the tool interpreter.
2. `apatch.py` parses CLI options, resolves the handoff, verifies that the current directory belongs to the expected Git repository, and loads global and target-project configuration.
3. Project runtime artifacts are excluded locally from Git, log context is established, and the state file is opened under a lock. Legacy runtime data is migrated when appropriate.
4. `Workflow` chooses the relevant action under LOOSE, STRICT, or FORCE, reports the current branch/phase, and coordinates the owning helpers.
5. Helpers inspect the actual filesystem/Git/GitHub state before side effects, update the workflow checkpoint/history, and emit console and audit events.

`STS` takes an earlier, separate read-only path: it validates the repository and configuration, loads a snapshot without creating a state lock, and inspects local Git evidence. Interactive menu selection is also performed before opening the writable workflow state; choosing `STS` never enters the mutation path.

The CLI can be invoked interactively or by a direct operation number or mnemonic. Canonical action identities are defined centrally in `apatch_lib/workflow.py`.

## Module ownership

| Module | Responsibility |
| --- | --- |
| `apatch.py`, `apatch.sh` | CLI parsing, handoff discovery, mode selection, top-level error handling |
| `apatch_lib/workflow.py` | Action dispatch, phase coordination, menu and progress summaries |
| `apatch_lib/loose.py` | Incremental patch cycles, manual edits, accumulated commits, deferred push |
| `apatch_lib/force.py` | Explicit recovery of externally performed branch, patch, and Git operations |
| `apatch_lib/branch_patch.py` | Preparing branches and coordinating patch application |
| `apatch_lib/patch.py` | ZIP validation, safe member inspection, archive application |
| `apatch_lib/model.py` | Handoff and configuration schema, path validation, shared records |
| `apatch_lib/state.py` | Locked state persistence and atomic checkpoint updates |
| `apatch_lib/status.py` | Read-only current patch evidence, cautious next-action suggestions, and report formatting |
| `apatch_lib/patch_history.py` | Per-patch application journal and duplicate detection |
| `apatch_lib/migration.py` | Compatibility with earlier runtime file locations and names |
| `apatch_lib/gitutil.py` | Git subprocess wrappers, repository/branch/status helpers, canonical check execution |
| `apatch_lib/github.py` | PR discovery/creation, merge policy checks, safe merge coordination |
| `apatch_lib/logging_setup.py` | Contextual project logging and output redaction |
| `apatch_lib/local_ignore.py` | Protecting runtime files through local Git exclusions |

Keep safety validation close to its owning domain. Avoid distributing the same checks across unrelated mode implementations.

## Modes and operation semantics

`LOOSE` is the default. It tolerates a branch different from the planned feature branch, intentional manual edits, successive patch handoffs, and deferred commit/push. In LOOSE, action `CMT` creates a commit without pushing, while `PSH` publishes existing commits later.

`STRICT` enforces the expected branch, clean-tree state, and phase transitions. `FORCE` explicitly reconciles manual operations, but it does not bypass unsafe archive, Git remote, or GitHub policy checks. In STRICT and FORCE, the `CMT` action uses their combined commit/push workflow. The detailed action matrix is maintained in [Usage](USAGE.md#workflow).

The `skipApproves` option changes confirmation behavior; it does not disable validation. Because unattended actions can still modify a repository, callers must decide the target and affected files deliberately.

## Configuration and state ownership

**Global configuration:** `apatch.conf` beside `apatch.py` defines downloads location, default remote/base branch, runtime artifact names, merge policy, and archive limits.

**Target configuration:** `<target>/.apatch/config.yaml` defines canonical check commands, with optional overrides for relative logging/state/history locations. Validation refuses invalid or symlink-escaped paths.

**Target runtime artifacts:** by default:

- `.apatch/apply_patch.state.json` and its lock;
- `.apatch/applied_patches.txt` and its lock;
- `.apatch/logs/apatch.log`;
- `.apatch/backups/` for recoverable overlap backups when created.

These are **not** source files in the `apatch` tool repository. They belong to each target repository separately and should remain outside version control. The committed `.apatch/config.yaml` is different: it is a project-owned contract describing checks.

The workflow checkpoint tracks individual patch cycles; the applied-patch journal records successful applications with timestamp, ZIP name, planned branch, and actual branch. Journal entries are not evidence of a later commit or push. Migration preserves prior data rather than discarding older files.

New branch actions record `branch_origin` as `CREATED` or `REUSED` once the decision has actually been made. Older checkpoints lacking this field show `UNKNOWN` instead of a guessed origin. `STS` compares checkpoints with local Git facts and distinguishes `VERIFIED`, `RECORDED`, `UNKNOWN`, and `CONFLICT`. Offline PR, push, and merge claims remain unverified. Recommendation logic depends on the actual saved phase, mode, branch, and observed conflicts, without granting any action new authority.

## Safety and recoverability

- Archive extraction validates the handoff and ZIP before applying file changes. Unexpected overlapping dirty files require consent and a backup; ZIP replacement is not a semantic merge.
- Git preconditions are checked against the actual repository state. Push must be fast-forward and never uses `--force`.
- GitHub PR merge remains guarded by configured review and required-check policies. All `gh` commands use a configurable deadline separate from canonical checks. PR creation first queries all base branches in one listing; a retry reuses an already-created matching PR instead of issuing a second create. A timeout during creation leaves the remote outcome uncertain and does not advance the local checkpoint. In LOOSE/FORCE, local base-branch synchronization uses fast-forward-only Git operations before an optional GitHub PR status reconciliation; an API timeout never fabricates a merged/synced workflow phase. STRICT still requires live merge confirmation. A successful remote merge can be followed by a separately retryable local synchronization action.
- State files and journals use locking/atomic persistence. Later invocations can reconcile interrupted operations rather than assuming the previous step completed.
- Multi-patch LOOSE workflows retain earlier checkpoints even when a new handoff ZIP is selected. A commit may include several applied patches.

## Output and observability

The console reports operation identity, branch, phase, HEAD and working-tree transitions, Git operation outcomes, and canonical-check output. The project log records invocation and command metadata plus bounded failure diagnostics. **Canonical-check stdout/stderr is not copied wholesale into the log.**

Error text is actionable, but a successful CLI return does not imply that the repository changed: an action can be cancelled or already satisfied. See [Usage](USAGE.md#console-progress-and-results) and [Usage](USAGE.md#logging) for operational behavior.

## Extension points

Before adding an operation or changing a mode, inspect the owning helper, CLI parsing, status messages, state/history implications, and black-box tests. Update the public operation matrix in Usage and regression coverage together. For significant behavior changes, establish a normative SDD spec first; the initial spec will be introduced separately.
