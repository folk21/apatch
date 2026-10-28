# Security and Recovery Boundaries

`apatch` coordinates untrusted patch archives with a developer's existing Git repository. It is **not a sandbox** and cannot validate the intent of generated source code.

## Trust boundaries

| Input | Enforcement | Remaining risk |
| --- | --- | --- |
| ZIP contents | Bounded size/count, verified digest, safe paths, regular files, duplicate and parent/child collision checks | Source changes may be malicious or logically incorrect |
| `.apatch/` | Ordinary archive files and `delete_paths` cannot change runtime state or project-owned policy; only validated metadata members are accepted | A developer can intentionally edit policy outside the ZIP workflow |
| Project checks | Explicit argv from tracked `.apatch/config.yaml`; no implicit shell; total deadline (default 900s) plus no-output deadline (default 30s) | Check commands and scripts they invoke run with the developer's normal OS permissions; long silent checks need a larger idle limit |
| Git and GitHub | Live branch/commit/PR checks, fast-forward restrictions, review/CI policy, bounded GitHub reads | A remote mutation can succeed despite a lost response; reconcile before retry |
| Cached state | Atomic writes, stable advisory locks, restricted file paths | Checkpoints are records, not independent evidence that remote actions completed |

## Applying and recovering safely

1. Inspect the ZIP and its embedded handoff before using unattended operations. Avoid automatic PR merge for archives that have not undergone code review.
2. The extractor validates all target paths and prepares file contents before replacing destination files. This reduces predictable partial writes but **does not make a multi-file patch atomic across a crash or disk failure**.
3. On an interrupted `APL`, inspect `git status`, `.apatch/apply_patch.state.json`, the applied-patch journal, and `.apatch/backups/` if overlap backups were created. Do not blindly repeat extraction or delete the recorded state.
4. `skipApproves=true` only disables interactive confirmation. It does not bypass Git, ZIP, branch, or GitHub safety checks. In LOOSE mode, it can also auto-approve an explicitly warned post-check manual change, so unattended publication deserves extra scrutiny.
5. `STS` is read-only and uses local evidence; GitHub outcomes marked `UNKNOWN_REMOTE_RESULT` require a separate live check.
6. An explicitly selected previously applied ZIP is eligible for replay-free continuation only when its digest, checkpoint signature, latest structured applied-history entry, successful `APL` run, and live local Git context agree. The tool rechecks these facts under its state lock before switching the active cached selection. Missing or conflicting evidence prevents selection; it never justifies re-extraction, state rewriting, or a branch reset. A verified `APL`/`BRN` sequence prefix records `NO_OP` attempts, not fabricated successful applications or branch operations.

Runtime locking uses POSIX `fcntl` and is targeted at Linux and macOS. Native Windows is not a supported/tested target. CI verifies behavior on both Linux and macOS; actual GitHub integration is covered by mocks, not live publication tests.

## Internal guarded commit scope (FS-04)

The internal feature-session commit path records incoming ZIP footprints and
pre-existing staged paths at `APL`. Before a guarded check, every changed
path must belong to an uncommitted, session-linked ZIP footprint or to a
separately and exactly accepted manual-path list. An earlier staged file is
never implicitly authorized. Unclassified paths and ambiguous rename,
copy or conflict statuses yield `WAITING_FOR_USER`, even with
`skipApproves=true`. Older checkpoints without reliable path provenance
must use the supervised LOOSE workflow; they are not automatically migrated.

The guarded path stages only those exact paths **before** canonical checks.
Its check record binds Git index/worktree bytes and modes, branch, HEAD,
accepted paths and the project checks-config revision. A check that modifies
source bytes fails verification; a second stable check is required. At
guarded commit time, the authorized paths must still equal the entire staged
scope, with no unstaged changes or stale evidence. The committed Git tree
must equal the verified staged tree; unexpected hook-driven commit changes
require explicit reconciliation.

Staging is a deliberate local mutation. If it is interrupted or checks fail,
the staged index remains intact for inspection. No automatic unstaging,
reset, push, PR creation or merge is attempted. Legacy direct LOOSE `CMT`
is unchanged, including its supervised `git add -A` behavior. The stricter
guarded path is available through LOOSE `goal=CHECKED|COMMITTED` only for
a uniquely verified session and exact ZIP-owned changed paths. This first
release has **no** manual-path approval flag: pre-existing staged or
unclassified manual paths block unattended goal execution even with
`skipApproves=true`. Use supervised direct LOOSE actions when a separate
manual change needs review. `planOnly=true` reads local evidence without
creating state or touching the Git index. Local goals do not authorize any
push, PR, merge or sync.

The project currently has no published license. Maintainers must select a license explicitly; its terms cannot be inferred from repository visibility.
