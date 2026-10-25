# APATCH-SUB-001 — Workflow Control, Patch Ordering, and Sequences

**Status:** DRAFT — first-priority P0 requirements.

**Parent:** [APATCH-SPEC-001](../spec-apatch-orchestrator.md). **Implementation stages:** [P0 plan](../../plans/apatch-orchestrator-implementation-plan.md#p0--first-priority).

## 1. Scope

Before scheduled quality checks and model reviews, implement these first-priority capabilities:

1. Read-only current patch status via `10 [STS]`.
2. Suggested next operation number/code after an action.
3. Independent project-level GitHub review-approval and required-CI gates.
4. Ordered `created_patches.txt` check against actual applied history.
5. `opSeq` execution with per-step console progress and actionable failure details.
6. Current explicit handoff JSON compatibility and a planned self-contained ZIP with project-local parameter caching.
7. Mandatory unfinished-feature-branch preflight before creating a new feature branch.
8. Bounded GitHub read retries and one repository-identity verification per operation.
9. A tool-wide, concurrency-safe progress ledger and an aggregated project overview.

All modes (`LOOSE`, `STRICT`, `FORCE`) SHALL retain their present safety rules and operation semantics.

The self-contained ZIP and apply-before-branch workflow in §3.6 is a **pending lifecycle change**, not a description of the installed CLI. Until its migration stage passes acceptance tests, the existing explicit-JSON and branch-before-apply contracts remain authoritative.

### 1.1 Current patch status (P0-0)

Register read-only operation `10 [STS]`, callable as `op=10`, `op=STS`, or from the numbered menu. All current action IDs `0..9` and their mnemonics remain stable. `STS` SHALL display the selected patch, planned and actual branch, whether the branch was **created** or **reused** when known, patch application, latest checks, commit, push, PR creation, PR merge, local-main synchronization, incomplete work, and a suggested next action by number/code. The original ZIP need not be present when a unique persisted workflow can be resolved. If several workflows match, ask for an explicit patch identifier; do not guess.

Every reported fact SHALL declare its evidence class: `VERIFIED` (observed from an authoritative available source), `RECORDED` (persisted but unverified), `UNKNOWN` (insufficient evidence), or `CONFLICT` (recorded and observed state disagree). A recorded SHA or PR number alone is not sufficient proof of a current commit/remote PR. Old state without branch provenance SHALL display `UNKNOWN`. Local Git inspection is the default; remote PR/merge verification is optional, bounded by timeouts, and MUST preserve useful offline output if unreachable. `STS` SHALL NOT mutate the worktree, Git state, checkpoint file, or operation history. It does not require confirmation.

Example:

```text
==> PATCH STATUS 10 [STS]
Patch: patch-B.zip
Actual branch: feature/work [VERIFIED]
Branch origin: REUSED [RECORDED]
Applied: YES [RECORDED]
Commit: PENDING [VERIFIED]
PR: UNKNOWN [remote not queried]
Next suggested: 4 [CHK] — Verify changes before commit
Alternative: 3 [APL] — Apply another handoff
```

## 2. Next-operation recommendation (P0-1)

After each completed standalone action, `apatch` SHALL report a **potential next operation** as both number and mnemonic, derived from the actual current phase, branch, selected mode, and action result. It MUST NOT imply that a recommended action has been executed or is already eligible when guards are unsatisfied.

| Completed operation | Potential next operation |
| --- | --- |
| `1 [BRN]` | `3 [APL]` |
| `2 [BAP]` | `4 [CHK]`; alternative `3 [APL]` with a different handoff |
| `3 [APL]` | `4 [CHK]`; alternative `3 [APL]` with a different handoff |
| `4 [CHK]` | `5 [CMT]` |
| `5 [CMT]` | `6 [PSH]` in LOOSE; `7 [PR]` if STRICT/FORCE also pushed |
| `6 [PSH]` | `7 [PR]` |
| `7 [PR]` | `8 [MRG]`, conditional on GitHub policy |
| `8 [MRG]` | `9 [SYN]` only when synchronization remains pending |
| `9 [SYN]` | None if fully synchronized; otherwise report pending reconciliation |
| `0 [EXT]` | None |

Actual branch/phase and live guards take precedence over this table. A no-op/cancelled/failed action MUST show its real outcome, not a success-path next step. An `opSeq` displays the next **scheduled** action independently of the next **recommended** action.

After P0.3c activates, the table's `BRN`/`BAP`/`APL` entries describe **legacy** branch-first workflows only. For a new patch applied on the base branch, `3 [APL]` SHALL instead suggest `1 [BRN]`; after that branch transition, `1 [BRN]` SHALL suggest `4 [CHK]`. `2 [BAP]` becomes an unsupported/deprecated action without reassigning its number. The CLI MUST continue to distinguish a new cycle from a legacy resumed cycle when recommending the next operation.

Example:

```text
==> RESULT 3 [APL]: SUCCESS (3.71s)
    Phase: new -> patch_applied

==> Next suggested: 4 [CHK] — Run canonical checks
    Alternative: 3 [APL] — Apply a new handoff
```

### 2.1 Console result and next-step emphasis (P0.4a)

The standalone, interactive, direct `op=`, and future `opSeq` paths SHALL share an unambiguous console outcome contract. Replace the existing `Finished without an error` result phrase with an explicit outcome keyword; merely returning without an exception MUST NOT be sufficient to report success:

- Show `==> RESULT <number> [<CODE>]: SUCCESS (<elapsed>s)` only when the requested action actually succeeded. Render the `SUCCESS` keyword **green** on a color-capable terminal.
- On a failed operation, show `==> RESULT <number> [<CODE>]: ERROR (<elapsed>s)` with `ERROR` **red**, followed by the underlying diagnostic and safe next/recovery action. Emit this result even if the operation raises before its ordinary completion summary. Preserve a nonzero exit status and the distinction between a proven failure and an uncertain external side effect.
- Explicit cancellation, no-op/already-satisfied actions, and indeterminate remote outcomes SHALL use distinct plain-text keywords (`CANCELLED`, `NO_OP`, and `UNKNOWN_REMOTE_RESULT`, respectively), never `SUCCESS` or an unjustified `ERROR`. These outcomes MUST preserve the actual phase and available evidence; the durable progress event schema may continue using its own specified result values (such as `FAILED`).
- Print the primary recommendation in a **separate, visually prominent line** with its number, mnemonic, and short explanation: `==> Next suggested: 4 [CHK] — Run canonical checks`. Highlight `Next suggested: 4 [CHK]` using bold cyan or a similarly distinct terminal style where supported. Keep alternatives visually subordinate. If no safe next operation is established, explicitly show `Next suggested: NONE` with an explanation, not a speculative success-path recommendation.
- When using `opSeq`, distinguish the **next scheduled** sequence step from the **next suggested** lifecycle action; do not allow the latter to imply that a sequence will continue after a failure or cancellation.
- ANSI escape sequences SHALL be enabled only for an appropriate interactive terminal. Honor `NO_COLOR` and `TERM=dumb`; keep redirected output, logs, CI output without a TTY, and unsupported terminals free of escape sequences. Text labels, number/code, exit status, and diagnostics MUST remain comprehensible without color. No new mandatory third-party dependency is required.

The outcome and next-step emphasis SHALL work consistently in LOOSE, STRICT, and FORCE without changing action numbers, safety guards, state transitions, or Git/GitHub side effects. Terminal-color behavior SHALL be covered by positive and negative regression tests, including captured non-TTY output, a color-capable TTY, cancelled/no-op operations, thrown errors, and uncertain remote results.

## 3. Project-level review approval (P0-2)

The target repository's `.apatch/config.yaml` SHALL accept the optional boolean `require_review_approval`:

```yaml
schema_version: 1
require_review_approval: false
checks:
  - ["./run_tests.sh"]
```

- An explicit project value overrides the existing global `apatch.conf` value **only for this target repository**.
- When absent, inherit the global setting. The unchanged global default is `true` (unapproved PRs blocked).
- Invalid types/values MUST fail configuration validation rather than silently disable approvals.
- With `false`, an absent GitHub review approval does **not** block `MRG`; with `true`, retain the current `APPROVED` requirement.
- In both cases, verify PR identity/head SHA/base, mergeability, configured required CI checks, remote state, GitHub branch-protection/permissions, and consent (unless `skipApproves=true`). External GitHub rejection remains fatal.
- `skipApproves` MUST NOT override this setting. Before merging, print the effective value and its origin (`project` or `global`).

### 3.1 Independent project-level required-CI policy (P0-2b)

`require_review_approval` and `require_required_checks` are **independent**. Disabling PR review approval MUST NOT disable CI validation implicitly. The project `.apatch/config.yaml` SHALL additionally accept an optional boolean `require_required_checks`:

```yaml
schema_version: 1
require_review_approval: false
require_required_checks: false
checks:
  - ["./run_tests.sh"]
```

- Omitted `require_required_checks` inherits the global `apatch.conf` setting (default `true`); an explicit project value overrides it for this repository only.
- Invalid values (strings, integers, `null`, and collection types) MUST fail configuration validation.
- With `true`, the existing fail-closed behavior remains: a PR with no published checks, pending/failed checks, or failed required-check verification MUST NOT merge.
- With `false`, `apatch` skips **only its own GitHub CI-check gate**, including the requirement for a nonempty published check rollup. It MUST still enforce clean mergeability, matching PR identity/head/base, remote ref checks, configured review approval policy, and GitHub server-side protections and permissions. GitHub rejection MUST remain fatal.
- Before the merge attempt, print the effective review **and** CI policies, including each source (`project` or `global`). An explicit `false` is a conscious opt-out, not proof that CI passed. `skipApproves` remains independent.
- Project-local canonical commands configured in `checks` remain unchanged and SHALL NOT be skipped by `require_required_checks: false` when the separate `CHK` operation runs.

### 3.2 Unique, required handoff JSON selection (P0-2c; implemented legacy contract)

Every newly generated ZIP named `<patch-stem>.zip` SHALL have a handoff JSON with **exactly the same stem**, `<patch-stem>.json`. The static name `apatch_patch_params.json` SHALL NOT be used for newly generated handoffs. This removes ambiguity between multiple pending patches in the same downloads directory.

Each `apatch.sh` or `apatch.py` invocation SHALL receive an explicit positional handoff identifier, including `STS`, interactive menu mode, and future `opSeq` calls. There is no implicit project-derived JSON filename. An unqualified name without `.json` resolves to `<downloads_dir>/<name>.json`; an unqualified name already ending in `.json` resolves to the same configured directory. An explicit relative path (`./...`, `../...`) or absolute path resolves as supplied, appending `.json` if omitted. Existing explicit `.json` paths remain valid for backward compatibility; historical JSON contents and persisted patch state do not need migration.

```bash
apatch.sh apatch-PATCH-2026-10-24-00-42-example op=APL
apatch.sh /path/to/apatch-PATCH-2026-10-24-00-42-example.json strict op=CHK
apatch.sh apatch-PATCH-2026-10-24-00-42-example op=STS
```

Missing, empty, malformed, or nonexistent handoff identifiers MUST fail before Git/worktree effects with an actionable error. A malformed stem MUST NOT escape the downloads directory or select a different handoff implicitly. `--help` remains usable without a handoff. The read-only status operation still does not need the original ZIP, but **does** need an explicitly selected JSON; old no-JSON `STS --patch=...` access is intentionally withdrawn by this contract. In the chat handoff response, display the exact generated JSON **filename as standalone copyable text** in addition to its download link.

### 3.3 Mandatory single-active-feature-branch gate (P0-2d — emergency)

Every operation that is about to **create** a new `feature/...` Git branch SHALL first inspect all other local and published feature branches. This is a non-configurable safety gate: `LOOSE`, `STRICT`, `FORCE`, `skipApproves=true`, and any future `opSeq` MUST NOT bypass it.

1. Inspect local `refs/heads/feature/*` and remote `refs/heads/feature/*`, anchored to the configured base branch. Inspect all open GitHub pull requests with `feature/` heads when the configured remote is on GitHub. Do not rely only on the current branch or handoff checkpoint.
2. A different remote feature branch not provably integrated into the configured base, or any open feature-branch PR, SHALL block new branch creation with the message prefix **`сначала смерджи fb:`**, identifying the branch and relevant remote/PR evidence. A previously merged branch whose ref remains on GitHub SHALL NOT block merely because the ref was not deleted: accept proven Git ancestry or a verified matching `MERGED` PR head.
3. A different **local-only** feature branch with commits not present in the configured local base and not otherwise proven merged SHALL block with a separate message identifying the local branch and its outstanding commit count. A current feature branch with uncommitted changes SHALL also block moving work onto a fresh feature branch. A local branch with no unique commits does not count as unfinished work.
4. If required remote-ref or GitHub-PR status cannot be checked reliably (network timeout, authentication failure, incomplete listing, or invalid response), fail closed with an explicit diagnostic. Do not create a new feature branch based on stale or unknown remote state.
5. Run preflight immediately before `git switch -c` and before patch extraction and branch checkpoint changes. Failures MUST leave the intended target feature ref uncreated. Reusing or tracking an **already existing target branch** to finish earlier work does not create a new development cycle and SHALL remain possible under existing mode guards.

This gate is independent of project check schedules and CI/review settings. It intentionally serializes feature development within a target repository even when LOOSE normally permits manual work on different branches.

### 3.4 PR revision identity and historical merge recovery (P0-2e — emergency)

An existing PR, including a `MERGED` PR, SHALL only prove completion of the **exact feature revision** associated with the current patch cycle. GitHub `headRefOid`, the actual pushed Git commit, and the workflow's recorded `pushed_sha` (or verifiable recovery commit) SHALL agree. A source branch name, recorded PR number, or nonempty `mergedAt` on its own SHALL NOT prove that new commits entered the configured base.

1. `PR` SHALL prefer an existing unique `OPEN` PR matching the current pushed SHA and base. A mismatched open PR blocks creation. Historical merged/closed PRs referring to **earlier revisions** SHALL NOT be adopted and SHALL NOT prevent a separately confirmed, new PR from being created for a later SHA. A historical closed/merged PR referring to the *same* SHA SHALL block duplicate PR creation.
2. `MRG` in LOOSE/FORCE SHALL select a unique PR for the current SHA rather than the first historical `OPEN`/`MERGED` PR returned by GitHub. A mismatched historical `MERGED` PR SHALL stop before writing a checkpoint, switching branches, or syncing the base. If a different PR number is already recorded, an explicit `PR` reconciliation is required.
3. Both post-merge verification and `SYN` SHALL verify PR number, base/head names, source SHA, `MERGED` state, and `mergedAt` before asserting success. Multiple historical merged PRs for the same branch SHALL be disambiguated by the current SHA and recorded PR number. A GitHub merge commit may differ from the original feature commit under squash/rebase strategies; matching the exact **PR source revision**, not merge-commit identity, is the safety requirement.
4. A saved `synced` checkpoint recorded under older faulty logic SHALL NOT be treated as fresh proof on later `SYN`. Live mismatch or remote unavailability SHALL produce an explicit warning without silently clearing or validating the checkpoint. A developer-authorized `PR` action for the still-published feature head MAY replace the stale PR association, clear stale local-sync evidence, and return to `pr_created` so a distinct PR can be reviewed and merged normally.
5. This invariant is mandatory in all modes even when project settings disable review approval or CI checks. Failure to verify PR revision identity always fails closed; no new Git commits, destructive history rewrites, or automatic GitHub merge retries are permitted during recovery.

### 3.5 Bounded GitHub reads and per-operation identity reuse (P0-2f)

The `MRG` operation SHALL NOT repeat `gh auth status` and `gh repo view` when its preceding step in the **same invocation** already verified the same GitHub repository. It SHALL retain a verified repository identity only within the current operation. Before reusing the identity, it SHALL recheck the local Git remote URL and abort on repository drift. A new independent invocation SHALL verify identity again; there is no persistent or cross-process authorization cache.

1. Read-only GitHub CLI calls (`gh auth status`, `gh repo view`, `gh pr list`, `gh pr view`, and `gh pr checks`) MAY retry **once** after a recognized transient connection, DNS, GitHub gateway, or request-timeout failure. The timeout for each attempt remains bounded by `github_timeout_seconds`. Diagnostics SHALL identify the retry without leaking tokens or full command bodies.
2. Explicitly mutating GitHub calls (`gh pr create`, `gh pr merge`, and any future operation with uncertain external side effects) SHALL NOT be automatically retried. On timeout, report the uncertain outcome and require live reconciliation through `PR`, `MRG`, or `SYN` as appropriate.
3. Authentication failures, permission denials, invalid command arguments, non-transient API rejections, and invalid response data SHALL fail without retries. The implementation SHALL NOT convert connection failures into successful review, CI, PR, or merge evidence.
4. No retry or identity reuse may bypass PR source SHA, base, status, merge timestamp, branch protection, review policy, CI policy, or explicit confirmation rules. The retry mechanism SHALL apply to all modes and preserve the console's operation and failure reports.

### 3.6 ZIP-only handoff, cached parameters, and apply-before-branch lifecycle (P0.3c; pending)

**Single-file delivery:** A new patch ZIP SHALL contain one reserved regular-file metadata member at `<repository>/.apatch/params.json`, including validated schema-v1 handoff fields: `repository`, `feature_branch`, the ZIP's exact `patch_file` basename, complete `commit_message`, and optional `base_commit`/`delete_paths`. Its `patch_sha256` field MUST be absent: a ZIP cannot embed a hash of its own final bytes without circular dependency. `apatch` SHALL calculate SHA-256 after reading the finalized ZIP and save that digest in the local cache. The optional reserved `created_patches.txt` member retains all existing ordering and append-only safety rules. Neither reserved metadata member is an application source file, a changed path, or a Git commit candidate.

**Selecting and caching parameters:** On a new `APL` cycle, the developer identifies the ZIP by unique stem or ZIP basename, for example `apatch.sh <patch-stem> op=APL`. The tool SHALL locate it within configured `downloads_dir`, validate archive root, member type, filename/repository identity, ZIP content, and embedded handoff schema, then create or atomically replace `<target>/.apatch/params.json` with a verified canonical copy containing the calculated archive SHA. The cache must be project-local, Git-ignored, lock-protected, protected from symlinks/path traversal, and never overwritten with partially validated data. Preserve the former cache on a failed validation or write, and require an explicit selection when changing to a different unfinished patch cycle.

If a handoff JSON path is explicitly supplied, the old externally generated `.json` format SHALL continue to take precedence for migration and recovery. Otherwise, an invocation **without** a handoff (`apatch.sh op=BRN`, `apatch.sh op=CHK`, `apatch.sh op=STS`, or menu mode) SHALL load the current project's validated `.apatch/params.json`. The cached ZIP SHA and repository identity SHALL be checked before any later file-applying action. A missing, corrupt, unsafe, or ambiguous cache without an explicit handoff SHALL fail before side effects. Selecting a *new* ZIP still requires an explicit stem/basename; never guess the newest file in Downloads. Repeating `APL` with the current cached patch is a deliberate, guarded retry, not an automatic duplicate extraction.

**New operation order:** For a new patch cycle, the normal mandatory order SHALL be `APL` → `BRN` → `CHK` → `CMT` → `PSH` → `PR` → `MRG` → `SYN` as applicable. `APL` initially extracts verified patch files on the checked-out base branch **without creating a commit on base**. `BRN` then creates or safely adopts the proposed feature branch from the same base HEAD and carries the uncommitted patch changes across. Before creating a branch, require the existing mandatory local/remote unfinished-feature preflight, appropriate dirty-worktree checks, remote/base HEAD identity, and explicit consent. After the switch, atomically reconcile the checkpoint's actual `applied_branch` and source/verification evidence; record that extraction originally occurred on base while preserving truth in the applied-patch history. Changes MUST remain on the feature branch, with no commit on `main`. `CHK`/`CMT`/publishing SHALL NOT bypass the necessary feature-branch transition for a new cycle; interrupted `APL` or `BRN` SHALL be safely retryable without reapplying already extracted files.

**Retire `BAP` without reassigning operation IDs:** Remove `BAP` from the supported action menu and dispatch. A legacy `op=BAP` or numeric `op=2` SHALL stop with migration guidance, never run another operation. The existing numeric aliases for the remaining operations SHALL initially stay stable (`3 [APL]`, `1 [BRN]`): *first* and *second* mean chronological steps, not new numeric IDs. Existing branch-first workflows and persisted state SHALL remain resumable with their original evidence; any renumbering requires a separate versioned compatibility decision. FORCE and `skipApproves=true` cannot bypass extraction integrity, branch preflight, or safe recovery boundaries.

**Bootstrap:** The tool version that first implements this contract must still be distributed in the **old** ZIP+JSON handoff format because older `apatch` binaries cannot parse this new metadata or use a missing handoff argument. Once that upgrade is installed, new ChatGPT patch responses SHALL offer just one downloadable ZIP with a separately copyable basename and the full commit message in the chat. A plain standalone `params.json` download SHALL no longer be required. The external user's repository must not be modified merely to construct the patch response.

## 4. Ordered created-patch registry (P0-3)

### 4.1 Format and authority

`<target>/.apatch/created_patches.txt` is an optional UTF-8 text file with **one ZIP basename per line**, in original creation order. No timestamps, directories, comments, branches, or JSON. ChatGPT SHALL append each newly generated patch filename at the bottom without deleting/reordering existing entries.

The existing `.apatch/applied_patches.txt` (or configured history filename) remains the authoritative journal of successfully applied ZIPs, including legacy entries. Neither registry nor journal proves that a patch was committed, pushed, or merged.

The created registry is optional for backward compatibility. If absent and no incoming registry metadata is supplied, current behavior applies. If present, malformed names, duplicate lines, symlink/path escapes, and unreadable content MUST stop preflight with a clear message.

### 4.2 Preflight ordering rule

For selected ZIP basename `P`, let `C` be the ordered created registry and `A` the set of filenames in the applied journal. If registry tracking is active:

1. `P` MUST appear exactly once in `C`.
2. **Every registered patch preceding `P`** MUST appear in `A`.
3. `P` itself does **not** need to appear in `A` before its first application.
4. Later registered patches do not block applying `P`.
5. On the first missing predecessor, stop **before** branch creation, extraction, registry replacement, or other patch-side effects. Name the missing patch and selected patch.

Example:

```text
created_patches.txt:
  patch-A.zip
  patch-B.zip
  patch-C.zip

applied_patches.txt:
  patch-A.zip
```

Applying `patch-B.zip` is allowed. Applying `patch-C.zip` stops:

```text
STOP [PATCH_ORDER]: Patch patch-B.zip has not been applied!
Cannot apply patch-C.zip before earlier generated patches.
Created list: .apatch/created_patches.txt
Applied journal: .apatch/applied_patches.txt
Recovery: apply patch-B.zip or explicitly reconcile verified application history.
```

This check SHALL run for `BAP` and `APL` in all modes, including inside `opSeq`. `skipApproves=true` and FORCE MUST NOT silently skip it. A later explicit, evidence-based recovery mechanism MAY reconcile genuinely applied missing patches; simply deleting the created-list entry is not automatic recovery. Filename uniqueness is not content integrity: keep SHA-256 and existing duplicate-history checks independently.

### 4.3 Packaging and bootstrap

The future handoff transport SHOULD use a reserved ZIP metadata member `repository/.apatch/created_patches.txt`. The orchestrator SHALL validate this member against any current local registry and treat it as an **append-only metadata update**, not as a changed source file. It SHALL NOT count as a Git worktree change, be staged, or replace the local registry via normal ZIP extraction. Writes MUST be atomic and lock-protected; incoming metadata that deletes, changes, or reorders earlier lines MUST be rejected. If both an installed registry and incoming metadata exist, the incoming version must extend the existing prefix exactly.

**Current-version limitation:** The existing patch extractor treats every ZIP member as a source file, while `.apatch/` is Git-ignored. Therefore it is **not safe to include this registry as an ordinary ZIP member before the P0 metadata handler exists**: it can break changed-path verification. During bootstrap, ChatGPT may provide the updated ledger separately for manual placement; the normal handoff remains ZIP+JSON. The P0 implementation SHALL activate the reserved-member convention only after compatible parsing, application, and recovery tests pass.

ChatGPT must not invent missing historical lines. If the latest created registry is unavailable, request it or explicitly mark ordering coverage as incomplete. The presence of an older local registry still invokes the ordering guard.

## 5. Operation sequences (P0-4)

**Priority override (P0.4a0):** Deliver single-handoff `opSeq` and explicit
`skipApproves=true` support ahead of the P0.3c ZIP-only migration. On the
pre-P0.3c runtime, callers MUST still supply the existing JSON handoff and use
the currently supported branch-first sequence (`BRN,APL,...` or `BAP,...`) when
needed. Execute each action using the normal mode-specific handler and its
current guards. Reject ambiguous repeated application of the same ZIP, `EXT` or
`STS` within a sequence, and invalid/conflicting CLI choices before any action.
The future `APL,BRN,...` examples below apply only after P0.3c is installed.
P0.4b multi-handoff sequences remain separate; no automatic handoff switching
is implied by this priority change.

Current single-handoff examples for P0.4a0:

```bash
apatch.sh <json-stem> opSeq=BRN,APL,CHK,CMT,PSH skipApproves=true
apatch.sh <json-stem> opSeq=1,3,4,5,6 skipApproves=true
```

Omitting `skipApproves=true` retains normal step-level confirmations. An
unattended sequence MUST stop if confirmation is unavailable; approval bypass
never bypasses Git/ZIP/CI/review safeguards.

### 5.1 CLI

Add direct execution of comma-separated operation numbers or acronyms:

```bash
apatch.sh <patch-stem> opSeq=APL,BRN,CHK,CMT,PSH,PR skipApproves=true
apatch.sh <patch-stem> opSeq=3,1,4,5,6,7 skipApproves=true
```

These examples target the proposed P0.3c/P0.4 combination, not the current installation. `op` and `opSeq` are mutually exclusive. Whitespace around commas is permitted; unknown codes, empty elements, conflicting options, or a missing **explicit ZIP selection or safe current-project cache** MUST fail before the first side effect. `LOOSE` remains default. Every step SHALL use the same action implementation and checks as a standalone `op`, sequentially; it MUST refresh Git/GitHub state after the previous step. No hidden parallel execution or implied commit/push/merge is allowed.

Without `skipApproves=true`, ordinary step-level confirmations still apply; without a TTY, missing approval must produce an immediate actionable error. `skipApproves=true` skips confirmation prompts **only**, not safety validation, required CI, or GitHub policy.

### 5.2 Multiple patches in one sequence

Under P0.3c, `BAP` is unavailable. The P0 design proposes an optional `handoffSeq=<zip1>,<zip2>,...` parameter: successive ZIPs are consumed by `APL` steps; subsequent `BRN/CHK/CMT/PSH/PR` use the most recently selected verified handoff. No sequence may leave changes from a newly applied base-branch patch behind without the required `BRN` transition.

```bash
apatch.sh <patch-stem> opSeq=APL,BRN,APL,CHK,CMT,PSH,PR \
  handoffSeq=/path/first_patch.zip,/path/second_patch.zip \
  skipApproves=true
```

Without `handoffSeq`, actions use the existing selected/cache handoff. Duplicate `APL` steps with no explicit handoff change SHOULD be rejected at preflight with an explanation, not silently reapply the same ZIP. No implicit filename guessing or handoff replacement is allowed. Existing LOOSE accumulation and STRICT/FORCE guards still apply; handoff switches preserve all earlier records. This additional parameter is proposed and requires developer approval.

### 5.3 Console progress and failure contract

Before each action print `step i/N`, operation number/code, mode, handoff ZIP, branch, and phase. Show the actual command invocation with sensitive values redacted. After each step print the user-facing outcome (`SUCCESS`, `NO_OP`, `CANCELLED`, `ERROR`, or `UNKNOWN_REMOTE_RESULT`), elapsed time, resulting HEAD/phase if known, and the next scheduled action. Use the result and next-step emphasis from §2.1; `ERROR` is the console label for a known failure, while persistent event records continue to use `FAILED` where defined.

On failure, cancellation, timeout, or uncertain external effect, execution MUST stop without running subsequent steps. A failure MUST produce a nonzero exit status and report the exact failing step, underlying error, last completed step, known/uncertain repository state, remaining steps, and safe retry/reconciliation guidance. Cancellation MUST have a distinct reported outcome and MUST NOT be mistaken for success. No automatic rollback of a completed commit, push, or GitHub action is permitted.

Example:

```text
==> SEQUENCE 5/6: 6 [PSH] | LOOSE | feature/work
+ git push -u origin feature/work
STOP [REMOTE_TIMEOUT]: Step 5/6 (6 [PSH]) failed after 45.0s.
Last completed: 4/6 (5 [CMT]); commit=abc123...
Remote push outcome: UNKNOWN; no later step was executed.
Remaining: 7 [PR]
Recovery: check remote SHA and reconcile PSH before running PR.
```

Persist bounded, redacted diagnostics; do not persist entire canonical-check streams. For P0, restart/resume is **explicit** (`op=` or shorter `opSeq=`). Automatic background queues, conditional expression evaluation, retry loops for uncertain side effects, and rollback are out of scope.

## 6. Cross-project progress ledger (P0-5)

### 6.1 Purpose, location, and project identity

`apatch` SHALL retain a durable, human-readable history of its invocations across target Git repositories. This is a **tool-wide activity index**, not a replacement for each target's `.apatch/apply_patch.state.json` checkpoint, applied-patch journal, or Git/GitHub evidence. The default directory SHALL be `<apatch_installation>/.apatch/progress/`, excluded from the `apatch` Git repository. The initial implementation MAY make this location configurable; it MUST NOT silently place a global history inside whichever target project happens to be the current working directory.

The directory SHALL contain:

- `progress.json`: authoritative chronological cross-project event stream and a stable project registry, including each known project's last activity and recorded outstanding work.
- `<project>_progress.json`: a readable, derived per-project history. With unambiguous project names, examples include `apatch_progress.json` and `osmapdigger_progress.json`. The project root is the actual resolved target Git root, not only its basename or the handoff's `repository` field.
- A tool-owned lock file, excluded from Git, guarding all writes and repairs.

Two different directories can have the same project basename. The registry SHALL assign each project a stable identifier based on a normalized canonical root (and optionally a verified remote identity). The first unambiguous project may use `<name>_progress.json`; collisions SHALL receive a stable safe suffix, such as `<name>__<short-id>_progress.json`. Existing project histories SHALL NOT be silently overwritten or conflated because names match. Validate all generated filenames and prohibit symlink traversal.

### 6.2 Event schema, fidelity, and privacy

For every attempted top-level lifecycle operation (`BRN`, `BAP`, `APL`, `CHK`, `CMT`, `PSH`, `PR`, `MRG`, `SYN`, and read-only `STS`), record one bounded summary describing **what actually happened**. Future `opSeq` SHALL record one event per attempted constituent action with `sequence_id`, step index, and total. Record the final result even when an operation raises an exception; no event may claim a successful merge, push, or verification merely because its subprocess returned without raising.

Every event SHALL have at least:

| Field | Contract |
| --- | --- |
| `event_id`, `started_at_utc`, `finished_at_utc` | Unique identifier and ISO 8601 UTC timestamps; use a stable order for simultaneous invocations. |
| `project_id`, `project_name`, `project_root` | Canonical project identity and a useful location for reopening the project. |
| `patch_file`, `operation_code`, `operation_number`, `mode` | Selected patch and exact operation; mark fields `null` when unavailable during an early CLI failure. |
| `result`, `duration_seconds` | `SUCCESS`, `NO_OP`, `CANCELLED`, `FAILED`, or `UNKNOWN_REMOTE_RESULT`; unsuccessful or unverified outcomes remain distinct. |
| `phase_before`, `phase_after`, `branch_before`, `branch_after` | Recorded and observed local context, never invented from a planned branch. |
| `commit_sha`, `pr_number`, `next_suggested` | Last available recorded evidence and follow-up action, labeled as recorded rather than live GitHub verification. |
| `error_code`, `error_summary` | Short, bounded, redacted failure diagnostic; `null` on success. |

The files MUST NOT contain full canonical-check output, GitHub tokens, credential-bearing URLs, complete arbitrary shell arguments, environment variables, or unbounded exception traces. Save local files with restrictive permissions where supported. The CLI display SHALL label historical facts `RECORDED` and SHALL NOT poll all recorded GitHub repositories to manufacture live verification.

### 6.3 Concurrency, atomicity, and recovery

`progress.json` SHALL be the single authoritative write source; per-project JSON files are derived views. A writer SHALL acquire an **exclusive interprocess lock**, read and validate the latest master contents under that lock, append exactly one event (deduplicated by `event_id` if resuming), atomically replace and fsync the master file, and regenerate the affected project view using an atomic replacement. The lock SHALL be released on success and failure. A second process MUST NOT lose events or overwrite another process's project summary.

Multi-file replacement is not inherently transactional: after an interruption between master and per-project writes, the next writer SHALL rebuild the derived file under the same lock. The information command SHALL be able to show the authoritative master view even when a derived file is missing or stale. Malformed existing master data, unsafe paths, permission failures, or lock contention SHALL produce explicit diagnostics; never delete or silently reset historical entries. A progress-storage error after a successful Git/GitHub side effect SHALL be reported as a **separate history warning**, without pretending the side effect failed or automatically undoing it. Tool behavior remains usable if the installation location is read-only, with a visible `PROGRESS_UNAVAILABLE` warning.

### 6.4 Read-only global overview and configuration

Support the special information command `apatch.sh info=PROGRESS` (equivalently `apatch.py info=PROGRESS`) from the tool's installation directory or any working directory. This is an explicit exception to the handoff-required rule: it SHALL NOT require a patch JSON, an active target project, GitHub authentication, or project-local `.apatch/config.yaml`. `--help` and all existing `op`/mode syntax remain compatible. Invalid combinations of `info=PROGRESS` with a lifecycle operation SHALL fail before side effects.

The overview SHALL show the **8 most recent events across all projects** and the **3 most recent events for each known project**, sorted newest first by UTC timestamp and stable event ID. Display the project root, last recorded operation/result/time, latest branch/patch, potential next step, and unfinished or uncertain work prominently. An empty index SHALL produce a useful message; it SHALL NOT scan arbitrary directories on the machine.

The global `apatch.conf` SHALL offer `progress_global_limit = 8` and `progress_project_limit = 3`, both positive, bounded integers; invalid values SHALL fail validation. Config values affect presentation only and SHALL NOT truncate persisted history. The progress index SHALL also support later filters such as `info=PROGRESS project=<id>` and a project-only overview without changing the initial read-only contract.

### 6.5 Migration and discovery

There is no automatic knowledge of target projects used **before** this feature starts recording. Register projects on their first subsequent invocation; if a matching legacy checkpoint exists, it MAY be shown as `RECORDED` evidence but never synthesized as a successful historic command event. Do not invent previous timestamps, PR approvals, merges, or sequence order. An optional explicit import/scan operation can be specified later, with a developer-selected directory scope and no unbounded filesystem discovery. Missing global progress data is normal on first use; a malformed existing history is not.

## 7. Acceptance scenarios

| ID | Input or state | Expected behavior |
| --- | --- | --- |
| AC-01 | Successful `APL` | Suggest `4 [CHK]`, mention alternative `3 [APL]` |
| AC-02 | `MRG` already synchronizes local base | Report completion instead of redundant `SYN` |
| AC-03 | Project `require_review_approval: false`, review missing | Local review gate opens; all other merge gates remain |
| AC-04 | Project override absent | Current global/default review policy remains |
| AC-05 | Created `A,B,C`, applied `A`, selected `B` | Apply is allowed, since current `B` is not a missing predecessor |
| AC-06 | Created `A,B,C`, applied `A`, selected `C` | Stop with missing `B` before side effects |
| AC-07 | Registry reorder/duplicate or incoming prefix mismatch | Block without truncation or overwrite |
| AC-08 | Registry absent in old handoff | Preserve current application behavior |
| AC-09 | `opSeq=APL,BRN,CHK` after P0.3c | Apply on base, move changes to feature, then verify in order with detailed progress |
| AC-10 | `opSeq=APL,BRN,APL` plus two explicit ZIP handoffs | Use declared ZIP order and regular mode guards without reapplying the first archive |
| AC-11 | Invalid `opSeq`, conflicting `op`, or duplicated `APL` without another explicit ZIP selection | Reject before any Git/archive mutation |
| AC-12 | Second or later sequence step fails | Stop immediately, show failed/last-completed steps, preserve previous effects |
| AC-13 | `skipApproves=true`, required CI fails | No policy bypass; fail and stop sequence |
| AC-14 | PR or merge CLI timeout | Mark remote result unknown, do not automatically repeat side effects |
| AC-15 | `op=STS`, active patch is applied but not committed | Report branch/application evidence, pending commit, and suggested action without mutation |
| AC-16 | Saved PR number but remote access disabled or unavailable | Show `RECORDED` or `UNKNOWN`, never fabricate remote verification |
| AC-17 | Old state lacks branch creation/reuse provenance | Show origin `UNKNOWN` without failing the status operation |
| AC-18 | Two matching workflows or conflicting saved/local SHA | Request disambiguation or report `CONFLICT`; never silently select or modify state |
| AC-19 | Project `require_required_checks: false`, PR has no published CI, approvals independently disabled | Local CI gate permits merge attempt; server rejection still stops it |
| AC-20 | Project CI override absent, no published checks | Inherited default retains `PR has no published checks` failure |
| AC-21 | Project CI override `false`, PR identity/head invalid or GitHub merge command rejects | Merge remains blocked; no false `merged` checkpoint |
| AC-22 | Two ZIPs with distinct stems; invoke CLI with a stem | Each ZIP has a same-stem JSON; CLI resolves the chosen stem under downloads without a default |
| AC-23 | Missing handoff positional, malformed stem, no-JSON `STS --patch` | Fail early without Git changes; explicit `.json` paths still work |
| AC-24 | Completed ChatGPT patch handoff | Response includes both linked artifacts and a separate copyable JSON filename |
| AC-25 | Previous local feature branch has commits not in `main`; new `BRN` in any mode with `skipApproves=true` | Stop before creating a new branch; identify local branch and pending commits |
| AC-26 | Previous remote-only feature branch not merged, or open GitHub feature PR | Stop with `сначала смерджи fb:` and identify the blocking branch/PR |
| AC-27 | Previous local/remote feature branch already merged into base | Permit new branch creation; do not demand deletion of merged refs |
| AC-28 | Feature preflight cannot reliably query required remote evidence | Fail closed and explain the unavailable validation; no new branch or patch application |
| AC-29 | Target feature branch already exists and is being resumed | Preserve current branch-adoption behavior; do not treat resuming as creating new feature work |
| AC-30 | PR #5 is `MERGED` at an older SHA; current patch was pushed at a different SHA | `MRG` refuses to adopt PR #5; no `merged`/`synced` checkpoint or local base switch |
| AC-31 | A historical merged PR and a new open PR share the same branch | `PR` creates or selects only the current SHA's open PR; `MRG` and `SYN` select it by SHA and identity |
| AC-32 | A closed/merged PR already references the exact current pushed SHA | `PR` blocks a duplicate rather than creating another PR for the same revision |
| AC-33 | A previous `synced` checkpoint references a merged PR at a different SHA | Subsequent `SYN` warns and retains evidence; explicit verified `PR` can replace the stale association |
| AC-34 | CI and review approvals are both disabled | Historical merged PR at a different SHA remains rejected; unrelated opt-outs do not bypass identity |
| AC-35 | `MRG` executes recovery, merge, and base sync for one GitHub repository | Resolve `gh auth status`/`gh repo view` once within the invocation; still detect a changed local Git remote before downstream steps |
| AC-36 | First read-only GitHub lookup times out, second succeeds | Retry once with visible bounded diagnostic; preserve the configured per-attempt timeout |
| AC-37 | `gh pr create`/`gh pr merge` returns a timeout after an uncertain side effect | Never auto-repeat the mutating command; retain the current checkpoint until explicit live reconciliation |
| AC-38 | GitHub denies access, returns invalid data, or two read retries time out | Fail closed without fabricating CI, approval, merge, or synchronization success |
| AC-39 | Two target projects execute overlapping operations | Both events persist without loss in `progress.json` and the correct per-project views under one process-shared lock |
| AC-40 | Run `apatch.sh info=PROGRESS` outside a target Git repository | Show 8 latest global and 3 latest per-project recorded events without a handoff or any Git/GitHub mutation |
| AC-41 | Global `progress_global_limit`/`progress_project_limit` are customized | Apply display limits independently; reject invalid values; retain the full ledger |
| AC-42 | Crash between updating `progress.json` and a derived project JSON | Rebuild the project view from the master on the next write; read-only overview remains accurate |
| AC-43 | Two project directories share a basename | Preserve separate stable project IDs and collision-free per-project history files |
| AC-44 | Operation fails after an ambiguous PR/push timeout or is cancelled | Record `FAILED`/`UNKNOWN_REMOTE_RESULT`/`CANCELLED` accurately and include short recovery context, not a false success |
| AC-45 | A project was used before the progress feature, or the tool installation is read-only | Do not invent past events; show partial history or `PROGRESS_UNAVAILABLE` without corrupting target workflows |
| AC-46 | Successful `APL` in an ANSI-capable terminal | Show green `SUCCESS` in the result banner and a prominent, separately labeled `Next suggested: 4 [CHK]` with number/code; the result must be readable without interpreting colors |
| AC-47 | Operation throws an error, is cancelled, is already satisfied, or has an uncertain remote outcome | Show red `ERROR` only for a proven failure; distinguish `CANCELLED`, `NO_OP`, and `UNKNOWN_REMOTE_RESULT`, and provide a safe next/recovery step without claiming false success |
| AC-48 | Output is redirected, `NO_COLOR` is set, or `TERM=dumb` | Never emit ANSI escapes; preserve exact readable outcome labels and next-action number/code in all modes and in `opSeq` |
| AC-49 | New self-contained ZIP contains a valid `.apatch/params.json` member and no external JSON | `APL` loads metadata, computes final ZIP SHA, applies source files, and writes a Git-ignored, verified target-local cache without staging metadata |
| AC-50 | `APL` completed on base with uncommitted changes, then `BRN` is called without a handoff | Read cached parameters; verify base HEAD and changed paths; enforce the unfinished-feature gate; carry the changes to feature branch and suggest `CHK` without committing on base |
| AC-51 | No explicit handoff and cache is missing, malformed, a symlink, or belongs to another repository | Fail before Git/archive mutation; do not guess a ZIP or overwrite previous cache |
| AC-52 | ZIP embeds an incorrect repository/patch name, unsafe metadata member, or missing mandatory field | Reject before extraction; preserve existing cached parameters and earlier work |
| AC-53 | Existing handoff JSON supplied explicitly or a legacy branch-first checkpoint resumed | Retain legacy format support and safe recovery; never discard or silently migrate earlier commits/history |
| AC-54 | `BAP` selected after the new lifecycle is enabled | Show a specific deprecation error for `BAP`/numeric `2`; keep numeric identifiers for other actions unchanged |
| AC-55 | Crash between ZIP application, cache replacement, and feature-branch creation | Preserve evidence and previous cache where necessary; safely retry/reconcile without duplicate application or an unintended main-branch commit |

## 8. Open decisions

1. Approve `handoffSeq` for multiple different patches in one `opSeq` invocation (or select a different handoff-selection syntax).
2. Approve the reserved `.apatch/created_patches.txt` ZIP metadata member and separate-file bootstrap before support is implemented.
3. Approve strict rejection when a selected patch is missing from an existing created registry, rather than auto-registering it.
4. Confirm the suggested default `<apatch_installation>/.apatch/progress/` and whether a future override for read-only installations should follow an OS-specific user-data directory.
5. Confirm retaining the numeric operation aliases (`3 [APL]`, `1 [BRN]`, reserved `2 [BAP]`) during the ZIP-only migration rather than renumbering and breaking existing scripts.

Mark this sub-spec `ACCEPTED` only after these choices are resolved. No implementation is authorized by this DRAFT.
