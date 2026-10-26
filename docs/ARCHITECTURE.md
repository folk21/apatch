# Architecture

This document describes the implemented components and operational boundaries of `apatch`. It is **descriptive**, not a normative SDD specification. See [Usage](USAGE.md) for user-facing commands, and [Development](DEVELOPMENT.md) for testing and contribution rules.

## Purpose and trust boundaries

`apatch` is an external Python CLI that orchestrates changes in an **existing target Git repository**. The installed `apatch` directory contains code and `apatch.conf`; the current working directory identifies the target Git repository. The two must not be confused.

Inputs include an untrusted ZIP with embedded handoff metadata (or a legacy external JSON), a verified cached handoff, repository-local `.apatch/config.yaml`, local Git state, and optional GitHub PR state. Relevant boundaries are:

- ZIP members, requested deletions, and configured paths must not escape the target repository or modify Git metadata.
- Manual working-tree changes are user-owned; patch application must avoid silent data loss.
- A handoff describes intended operations; neither it nor persisted workflow state proves that Git or GitHub operations occurred.
- GitHub status, approvals, and remote refs are external facts and may change between calls.
- Runtime diagnostics may reveal source text or credentials, so logging has bounded and redacted content.
- Embedded ZIP metadata does not authorize changes to project policy or `.apatch` runtime files.

## Execution flow

1. `apatch.sh` normalizes supported shell-friendly mode arguments and invokes the tool interpreter.
2. `apatch.py` parses CLI options, identifies the actual target Git repository, and loads configuration. For a new cycle it verifies an explicitly selected ZIP and embedded handoff; for continuation it loads `.apatch/params.json`. Explicit legacy JSON selection remains supported.
3. Project runtime artifacts are excluded locally from Git, log context is established, and the state file is opened under a lock. Legacy runtime data is migrated when appropriate.
4. `Workflow` chooses the relevant action under LOOSE, STRICT, or FORCE, reports the current branch/phase, and coordinates the owning helpers.
5. For lifecycle actions 1–9, a project-local `STARTED` run is atomically recorded before the helper acts. Helpers inspect actual filesystem/Git/GitHub state, update workflow checkpoints, then atomically record a terminal run outcome and bounded evidence. After a successful initial `APL`, the validated handoff and archive digest are cached locally.
6. Each attempted action also produces a bounded tool-global progress event. Events are buffered while the target checkpoint lock is held and persisted only after releasing it; progress failures cannot undo or change the reported Git/GitHub outcome. The global event ID matches the project run ID for actions 1–9.

`STS` takes an earlier, separate read-only path: it validates the repository and configuration, loads a snapshot without creating a state lock, and inspects local Git evidence. Interactive menu selection is also performed before opening the writable workflow state; choosing `STS` never enters the mutation path.

`AUD` (`11`) also dispatches before any runtime artifact, progress recorder, or writable state lock is initialized. It first reads the installation-local global progress master without creating or repairing it and renders the latest attempted/successful operations for known projects as **recorded** history. Invalid optional global activity produces a bounded warning without suppressing independent repository findings. `apatch_lib/reconciliation.py` then reads the generation and application journals, historical workflow/run records, and local Git refs and objects. Its audit result separates recorded claims from verified facts, unknown coverage, and direct conflicts. All optional remote requests are explicitly gated by `verifyRemote=true`, bounded by configured timeouts, and converted to unknown coverage on failure. Malformed project-local state or symlinked journal sources are rejected. The report never repairs checkpoints, registries, PRs, or Git branches. Console inventory and findings are bounded; underlying stored history is not truncated or automatically deleted.

The CLI can be invoked interactively, by a direct operation number/mnemonic,
or with a validated comma-separated `opSeq`. A sequence reuses the same action
dispatch, refreshes branch/phase checks before each operation, and halts on an
error, cancellation, uncertain remote mutation, or unverified state-changing no-op. Read-only `STS` may be
included anywhere, and a `SYN` that positively reverifies a synchronized base
and matching merged PR is treated as already satisfied. Progress output uses
canonical operation numbers rather than batch-relative ordinals. The sequence
does not roll back completed Git side effects. A singleton `opSeq=STS` uses the
same early read-only path as direct `STS`. Canonical action identities are
defined in `apatch_lib/core/actions.py`. A singleton `opSeq=AUD` takes the
standalone audit path; combined audit/lifecycle sequences are rejected.

An explicit `handoffSeq` maps one distinct, verified self-contained ZIP to each
`APL` in an `opSeq`. All selected ZIPs are validated before the writable state
lock is acquired, including repository identity and the shared feature branch.
For multi-ZIP sequences, LOOSE alone permits `APL,BRN,APL,...` on the same
feature branch. The second and later ZIPs require a prior pending, recorded
patch on that branch at the current HEAD; BRN cannot be repeated and publishing
cannot start before the last APL. Each APL owns a separate workflow checkpoint
and applied-patch history entry. Previously applied changes and backups remain
in place; one deferred CMT can record the same commit SHA against all pending
patch checkpoints. The cache is updated only after each successful APL, so
`STS` and later invocations use the latest successfully applied handoff. A
failed action stops the sequence without undoing earlier effects.

A separately selected repair ZIP may use explicit LOOSE `followup=true` after
an earlier invocation has applied its predecessor and moved uncommitted files
onto the planned feature branch. Before superseding any previous checkpoint,
the tool requires a matching pending workflow at the same HEAD and remote,
uncommitted changes, and the current planned feature branch. Extraction still
uses the normal overlapping-file approval, backups, registry ordering and
per-ZIP checkpoints. This is not an implicit multi-ZIP replay and cannot
be combined with `handoffSeq`.

Applied-ZIP history prevents accidental replay: unattended `APL` checks for
duplicates before previous-cycle reconciliation, overlap approvals, or file
replacement. A deliberate interactive reapplication still requires explicit
duplicate confirmation. A completed `APL` reports success from extraction and
persisted checkpoint evidence, even when Git HEAD, phase, and the changed-path
set do not vary; filesystem path-set equality alone is not a reliable no-op test.

`RemoteOutcomeUnknown` identifies GitHub PR create/merge transport failures and
unverifiable post-mutation responses without conflating them with known
failures. The workflow displays `UNKNOWN_REMOTE_RESULT`, preserves the
underlying nonzero exit status, and requires explicit live PR reconciliation.
`apatch_lib/console.py` centralizes TTY-aware styling for outcome labels and
the primary numbered next-action recommendation; non-TTY and `NO_COLOR` output
remain machine-readable.

LOOSE `CHK` fingerprints file bytes and Git index metadata before and after
configured checks. When a check modifies the worktree without changing the
set of Git status paths, `apatch_lib/loose.py` raises a typed
`CheckWorktreeChanged` failure after persisting `patch_applied` and clearing
previous verification evidence. The shared action presentation records an
`ERROR`/`FAILED` attempt, emits an actionable, TTY-highlighted `CHK`
recommendation, and the sequence stops before later mutating steps. This
avoids classifying changed bytes as `NO_OP` merely because branch, HEAD,
phase, and status paths stayed constant. No implicit reformat/retry, reset,
reapplication, commit, or GitHub mutation follows the failure.

## Module ownership

| Module | Responsibility |
| --- | --- |
| `apatch.py`, `apatch.sh` | CLI parsing, handoff discovery, mode selection, top-level error handling |
| `apatch_lib/workflow.py` | Action dispatch, phase coordination, menu and progress summaries |
| `apatch_lib/console.py` | Shared terminal-only result colors and next-operation emphasis |
| `apatch_lib/presentation/` | Action menu, console progress, and operation outcome classification |
| `apatch_lib/core/actions.py`, `core/enums.py` | Stable operation IDs and typed lifecycle/outcome values |
| `apatch_lib/core/paths.py` | Protected `.apatch` paths and generated runtime ignore patterns |
| `apatch_lib/storage/locking.py` | Shared no-follow, stable-inode advisory locking for persisted artifacts |
| `apatch_lib/sequence.py` | Sequence syntax validation, ordered dispatch, and fail-stop diagnostics |
| `apatch_lib/loose.py` | Incremental patch cycles, manual edits, accumulated commits, deferred push |
| `apatch_lib/force.py` | Explicit recovery of externally performed branch, patch, and Git operations |
| `apatch_lib/branch_patch.py` | Preparing branches and coordinating patch application |
| `apatch_lib/branch_guard.py` | Mandatory cross-mode preflight against unfinished local/remote feature branches and open GitHub feature PRs before creating a new branch |
| `apatch_lib/patch.py` | ZIP validation, safe member inspection, archive application |
| `apatch_lib/params_cache.py` | Restricted, locked, atomic persistence of a verified project-local handoff |
| `apatch_lib/model.py` | Handoff and configuration schema, path validation, shared records |
| `apatch_lib/state.py`, `apatch_lib/operation_events.py` | Locked schema-v2 checkpoint persistence, version migration, and durable operation-run evidence |
| `apatch_lib/progress.py` | Tool-global event summaries, cross-project identity, concurrency, privacy, and derived project histories |
| `apatch_lib/status.py` | Read-only current patch evidence, cautious next-action suggestions, and report formatting |
| `apatch_lib/reconciliation.py` | Global read-only history reconciliation, confidence/severity findings, optional bounded remote evidence |
| `apatch_lib/patch_history.py` | Per-patch application journal and duplicate detection |
| `apatch_lib/created_patches.py` | Optional ordered list of generated ZIP basenames and fail-closed application ordering |
| `apatch_lib/migration.py` | Compatibility with earlier runtime file locations and names |
| `apatch_lib/gitutil.py` | Git subprocess wrappers, repository/branch/status helpers, canonical check execution |
| `apatch_lib/github.py` | PR discovery/creation, merge policy checks, safe merge coordination |
| `apatch_lib/logging_setup.py` | Contextual project logging and output redaction |
| `apatch_lib/local_ignore.py` | Protecting runtime files through local Git exclusions |

Keep safety validation close to its owning domain. Avoid distributing the same checks across unrelated mode implementations.

## Modes and operation semantics

`LOOSE` is the default. It tolerates a branch different from the planned feature branch, intentional manual edits, explicit sequenced follow-up ZIP handoffs, and deferred commit/push. In LOOSE, action `CMT` creates a commit without pushing, while `PSH` publishes existing commits later.

`STRICT` enforces the expected branch, clean-tree state, and phase transitions. `FORCE` explicitly reconciles manual operations, but it does not bypass unsafe archive, Git remote, or GitHub policy checks. In STRICT and FORCE, the `CMT` action uses their combined commit/push workflow. The detailed action matrix is maintained in [Usage](USAGE.md#workflow).

New self-contained handoffs start with `APL` on a clean, remote-matched base, remain uncommitted, then use `BRN` to create the planned feature ref without losing changes. While this migration is pending, every other mutating operation is blocked, including FORCE and unattended sequences. The resulting checkpoint still has phase `patch_applied` but its `applied_branch` is the feature branch, allowing `CHK`. Legacy JSON handoffs and their branch-first checkpoints remain compatible; `BAP` is disabled for self-contained ZIP cycles while the legacy alias is retained for old clients.

The `skipApproves` option changes confirmation behavior across standalone and
sequence operations; it does not disable validation. Declined confirmations
remain distinct from success even if intermediate Git staging occurred. Because
unattended actions can modify a repository, callers must choose the target and
affected files deliberately.

## Configuration and state ownership

**Global configuration:** `apatch.conf` beside `apatch.py` defines downloads location, default remote/base branch, runtime artifact names, merge policy, and archive limits.

**Target configuration:** `<target>/.apatch/config.yaml` defines canonical check commands, with optional overrides for relative logging/state/history locations. Validation refuses invalid or symlink-escaped paths.

**Target runtime artifacts:** by default:

- `.apatch/apply_patch.state.json` and its lock;
- `.apatch/applied_patches.txt` and its lock;
- `.apatch/params.json` and its lock (verified current patch handoff; never Git-tracked);
- `.apatch/logs/apatch.log`;
- `.apatch/backups/` for recoverable overlap backups when created.

These are **not** source files in the `apatch` tool repository. They belong to each target repository separately and should remain outside version control. The committed `.apatch/config.yaml` is different: it is a project-owned contract describing checks.

The workflow checkpoint tracks individual patch cycles; the applied-patch journal records successful applications with timestamp, ZIP name, planned branch, and actual branch. Journal entries are not evidence of a later commit or push. Migration preserves prior data rather than discarding older files. The optional `.apatch/created_patches.txt` is a separate creation-order registry, excluded from Git through local rules. It can be maintained directly or updated by an append-only metadata member of a compatible ZIP handoff.

New branch actions record `branch_origin` as `CREATED` or `REUSED` once the decision has actually been made. Older checkpoints lacking this field show `UNKNOWN` instead of a guessed origin. `STS` compares checkpoints with local Git facts and distinguishes `VERIFIED`, `RECORDED`, `UNKNOWN`, and `CONFLICT`. Offline PR, push, and merge claims remain unverified. Recommendation logic depends on the actual saved phase, mode, branch, and observed conflicts, without granting any action new authority.

## Safety and recoverability

- ZIP inspection rejects path traversal, file/directory ancestor collisions, and ordinary ZIP edits or deletions under `.apatch/`. Only the two reserved metadata members (`params.json`, `created_patches.txt`) are allowed, and they are processed separately from source extraction. All output files are staged before replacing destinations, but a process crash during replacement is not a full filesystem transaction; inspect the `applying` checkpoint and Git changes before recovery.
- Unexpected overlapping dirty files require consent and a backup; ZIP replacement is not a semantic merge.
- `<repository>/.apatch/params.json` inside a ZIP is a reserved regular metadata member, not an extracted source file. It cannot contain the archive's own SHA-256; the final digest is computed from validated archive bytes and cached under the target repository's Git-ignored `.apatch/params.json` using no-follow checks, a dedicated lock, restrictive permissions, fsync, and atomic replacement.
- A failed cache write after `APL` does not imply failed extraction. A matching explicit ZIP selection can retry `BRN` from the recorded `patch_applied` checkpoint without extracting a second time, and restore the verified cache. If the ZIP has since been removed, an already valid cache permits normal continuation; no implicit ZIP guessing occurs.
- Git preconditions are checked against the actual repository state. Push must be fast-forward and never uses `--force`.
- Creating a new feature branch requires a shared, non-configurable preflight. It rejects unmerged remote feature refs, open GitHub feature PRs, and local feature refs with outstanding commits; it accepts provably merged old refs. Remote verification failures block creation, including in FORCE and with `skipApproves=true`. Reusing an existing target branch is not branch creation.
- Before BRN/BAP switches to or creates a feature branch, all modes validate the existing applied-patch journal under its advisory lock. Malformed historical entries abort before branch mutation with the offending line and expected field. The journal is never automatically repaired or discarded; correction requires reviewing the original record.
- Before BAP/APL is allowed to supersede an earlier patch checkpoint or change the branch/worktree, every mode checks the optional created-patch registry against the locked applied-patch history. Missing predecessors, missing selected entries, duplicate names, malformed UTF-8, or unsafe registry paths abort with actionable errors. Read-only validation runs again near extraction/adoption boundaries; FORCE and skipped confirmations do not bypass the guard. Projects without a created registry remain compatible.
- The reserved ZIP member `<repository>/.apatch/created_patches.txt` is parsed as metadata, not an extractable source path. Archive inspection verifies one regular-file member and the exact existing registry prefix; ordering applies to the incoming complete list. After source extraction and verification (or explicit FORCE adoption), an exclusive registry lock guards an atomic, fsynced append-only replacement before recording successful application. A failed metadata write leaves the previous registry intact and permits evidence-backed FORCE recovery. File-change fingerprints and Git staging never include this metadata.
- GitHub PR merge remains guarded by configured review and required-check policies. All `gh` commands use a configurable deadline separate from canonical checks. PR creation first queries all base branches in one listing; a retry reuses an already-created matching PR instead of issuing a second create. A timeout during creation leaves the remote outcome uncertain and does not advance the local checkpoint. In LOOSE/FORCE, local base-branch synchronization uses fast-forward-only Git operations before an optional GitHub PR status reconciliation; an API timeout never fabricates a merged/synced workflow phase. STRICT still requires live merge confirmation. A successful remote merge can be followed by a separately retryable local synchronization action.
- PR identity is scoped to the **source commit**, not only the branch name or an earlier PR number. `github.assert_pr_matches_revision` is shared by creation/recovery/merge/sync; FORCE filters historical PRs by the recorded published SHA before adopting merged state. An older merged PR cannot satisfy a later patch whose source branch advanced after that merge. Historical merged PRs may coexist with a new open or merged PR for the same branch. Recovery through an explicit new `PR` operation can replace a stale PR association while preserving earlier force audit events and avoiding mutation of Git history. Already-synced checkpoints are reverified on subsequent `SYN`, with uncertain/stale evidence reported rather than silently affirmed.
- Read-only GitHub CLI calls receive at most one retry for recognized transient network errors, with a configured timeout per attempt. GitHub-mutating commands (PR creation and merge) remain single-attempt and require an explicit recovery operation if their outcome is unknown. The LOOSE/FORCE `MRG` path passes a verified GitHub repository identity through recovery, merge, and base synchronization, avoiding duplicate authenticated repository lookups while checking that the local Git remote has not changed. A new invocation establishes its own trust context.
- State files and journals use locking/atomic persistence. Later invocations can reconcile interrupted operations rather than assuming the previous step completed.
- Multi-patch LOOSE workflows retain earlier checkpoints even when a new handoff ZIP is selected. A commit may include several applied patches.

## Output and observability

### Project-local execution journal (P1.1)

`<repository>/.apatch/apply_patch.state.json` combines existing `workflows` checkpoints with an append-only `operation_runs` list (schema version 2). Old schema-v1 files are read without disk modification and migrated on the first write, retaining unknown top-level fields and existing workflows. Each run records the action number/code, mode, repository, patch, UTC times, optional sequence identity, observed phase/branch/HEAD, and one of `STARTED`, `SUCCEEDED`, `NO_OP`, `CANCELLED`, `FAILED`, `INTERRUPTED`, or `INDETERMINATE`. Failed runs have short, fixed-category diagnostics, not raw command output. Verified effects are stored only where the corresponding workflow checkpoint supplies evidence; a successful record alone is not proof of current GitHub state.

An interrupted process can leave a `STARTED` entry. Later `STS` invocations warn without rewriting it or inventing a result; an explicit retry creates a new run after the normal live-state guards. `STS` does not create a project journal entry. The existing coarse-grained project state lock is held through lifecycle execution, with separate fsynced atomic `STARTED` and terminal file replacements under that lock. Releasing the lock across long-running operations is a separate concurrency improvement, not part of this behavior-preserving increment. At 100,000 runs or 32 MiB, writes stop for explicit archival rather than silently deleting history.

The console reports operation identity, branch, phase, HEAD and working-tree transitions, Git operation outcomes, and canonical-check output. The project log records invocation and command metadata plus bounded failure diagnostics. **Canonical-check stdout/stderr is not copied wholesale into the log.**

### Tool-global progress storage and read-only overview (P0.5a–P0.5b)

The installed tool stores private runtime activity at `<apatch_installation>/.apatch/progress/`, not in the target project. `progress.json` is the authoritative, append-only event index; `<project>_progress.json` files are derived views, with stable suffixes when project names collide. Events use canonical root-based project IDs, UTC timestamps, action IDs, outcome categories, checkpoint-derived context, and a shared `sequence_id` for batched operations. These fields are **recorded evidence**, not live GitHub verification. Events before installation of this feature are not synthesized or backfilled.

A separate global lock protects read-modify-write; fsynced atomic file replacement protects the master and views. On interruption between file replacements, the next writer reconstructs all project views from the master. A corrupt master or unsafe symlink fails closed without deleting previous events. An unwritable installation produces a `PROGRESS_UNAVAILABLE` warning but does not turn a successful repository operation into a failure. Read-only `info=PROGRESS` uses the authoritative master only, with stable newest-first sorting and configurable limits; it never opens target repositories, acquires a write lock, or contacts GitHub. The CLI dispatch precedes target-root discovery and checkpoint migration.

Error text is actionable, but a successful CLI return does not imply that the repository changed: an action can be cancelled or already satisfied. See [Usage](USAGE.md#console-progress-and-results) and [Usage](USAGE.md#logging) for operational behavior.

## Extension points

Before adding an operation or changing a mode, inspect the owning helper, CLI parsing, status messages, state/history implications, and black-box tests. Update the public operation matrix in Usage and regression coverage together. For significant behavior changes, establish a normative SDD spec first; the initial spec will be introduced separately.
