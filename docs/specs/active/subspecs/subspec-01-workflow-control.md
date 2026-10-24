# APATCH-SUB-001 — Workflow Control, Patch Ordering, and Sequences

**Status:** DRAFT — first-priority P0 requirements.

**Parent:** [APATCH-SPEC-001](../spec-apatch-orchestrator.md). **Implementation stages:** [P0 plan](../../plans/apatch-orchestrator-implementation-plan.md#p0--first-priority).

## 1. Scope

Before scheduled quality checks and model reviews, implement all five capabilities:

1. Read-only current patch status via `10 [STS]`.
2. Suggested next operation number/code after an action.
3. Independent project-level GitHub review-approval and required-CI gates.
4. Ordered `created_patches.txt` check against actual applied history.
5. `opSeq` execution with per-step console progress and actionable failure details.
6. Unique, explicitly selected handoff JSON names for every invocation.
7. Mandatory unfinished-feature-branch preflight before creating a new feature branch.

All modes (`LOOSE`, `STRICT`, `FORCE`) SHALL retain their present safety rules and operation semantics.

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

Example:

```text
==> END 3 [APL] | SUCCESS | phase=patch_applied
Next suggested: 4 [CHK] — Run canonical checks
Alternative: 3 [APL] — Apply a new handoff
```

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

### 3.2 Unique, required handoff JSON selection (P0-2c)

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

### 5.1 CLI

Add direct execution of comma-separated operation numbers or acronyms:

```bash
apatch.sh <patch-stem> opSeq=BRN,APL,CHK,CMT,PSH,PR skipApproves=true
apatch.sh <patch-stem> opSeq=1,3,4,5,6,7 skipApproves=true
apatch.sh <patch-stem> opSeq=BAP,APL,CHK,CMT,PSH,PR skipApproves=true
```

`op` and `opSeq` are mutually exclusive. Whitespace around commas is permitted; unknown codes, empty elements, conflicting options, or a missing handoff MUST fail before the first side effect. `LOOSE` remains default. Every step SHALL use the same action implementation and checks as a standalone `op`, sequentially; it MUST refresh Git/GitHub state after the previous step. No hidden parallel execution or implied commit/push/merge is allowed.

Without `skipApproves=true`, ordinary step-level confirmations still apply; without a TTY, missing approval must produce an immediate actionable error. `skipApproves=true` skips confirmation prompts **only**, not safety validation, required CI, or GitHub policy.

### 5.2 Multiple patches in one sequence

`BAP` already applies the current handoff. Consequently `opSeq=BAP,APL,...` requires selecting a **different handoff** for its second patch operation. The P0 design proposes an optional `handoffSeq=<path1>,<path2>,...` parameter: successive handoffs are consumed by patch-applying steps (`BAP` or `APL`); subsequent `CHK/CMT/PSH/PR` use the most recently selected handoff.

```bash
apatch.sh <patch-stem> opSeq=BAP,APL,CHK,CMT,PSH,PR \
  handoffSeq=/path/first_patch_params.json,/path/second_patch_params.json \
  skipApproves=true
```

Without `handoffSeq`, actions use the existing single handoff. A duplicate `BAP,APL` sequence with no handoff change SHOULD be rejected at preflight with an explicit explanation, not silently reapply the same ZIP. No implicit filename guessing or handoff replacement is allowed. Existing LOOSE accumulation and STRICT/FORCE gates still apply; handoff switches preserve all earlier records. This additional parameter is proposed and requires developer approval.

### 5.3 Console progress and failure contract

Before each action print `step i/N`, operation number/code, mode, handoff ZIP, branch, and phase. Show the actual command invocation with sensitive values redacted. After each step print outcome (`SUCCESS`, `NO_OP`, `CANCELLED`, `FAILED`, or `UNKNOWN_REMOTE_RESULT`), elapsed time, resulting HEAD/phase if known, and the next scheduled action.

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

## 6. Acceptance scenarios

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
| AC-09 | `opSeq=BRN,APL,CHK` | Execute in order and show detailed progress |
| AC-10 | `opSeq=BAP,APL` plus two handoffs | Use declared handoff order and regular mode guards |
| AC-11 | Invalid `opSeq`, conflicting `op`, or duplicate unqualified `BAP,APL` | Reject before any Git/archive mutation |
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

## 7. Open decisions

1. Approve `handoffSeq` for multiple different patches in one `opSeq` invocation (or select a different handoff-selection syntax).
2. Approve the reserved `.apatch/created_patches.txt` ZIP metadata member and separate-file bootstrap before support is implemented.
3. Approve strict rejection when a selected patch is missing from an existing created registry, rather than auto-registering it.

Mark this sub-spec `ACCEPTED` only after these choices are resolved. No implementation is authorized by this DRAFT.
