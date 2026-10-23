# APATCH-SUB-001 — Workflow Control, Patch Ordering, and Sequences

**Status:** DRAFT — first-priority P0 requirements.

**Parent:** [APATCH-SPEC-001](../spec-apatch-orchestrator.md). **Implementation stages:** [P0 plan](../../plans/apatch-orchestrator-implementation-plan.md#p0--first-priority).

## 1. Scope

Before scheduled quality checks and model reviews, implement all five capabilities:

1. Read-only current patch status via `10 [STS]`.
2. Suggested next operation number/code after an action.
3. Configurable project-level GitHub review-approval gate.
4. Ordered `created_patches.txt` check against actual applied history.
5. `opSeq` execution with per-step console progress and actionable failure details.

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
apatch.sh opSeq=BRN,APL,CHK,CMT,PSH,PR skipApproves=true
apatch.sh opSeq=1,3,4,5,6,7 skipApproves=true
apatch.sh opSeq=BAP,APL,CHK,CMT,PSH,PR skipApproves=true
```

`op` and `opSeq` are mutually exclusive. Whitespace around commas is permitted; unknown codes, empty elements, conflicting options, or a missing handoff MUST fail before the first side effect. `LOOSE` remains default. Every step SHALL use the same action implementation and checks as a standalone `op`, sequentially; it MUST refresh Git/GitHub state after the previous step. No hidden parallel execution or implied commit/push/merge is allowed.

Without `skipApproves=true`, ordinary step-level confirmations still apply; without a TTY, missing approval must produce an immediate actionable error. `skipApproves=true` skips confirmation prompts **only**, not safety validation, required CI, or GitHub policy.

### 5.2 Multiple patches in one sequence

`BAP` already applies the current handoff. Consequently `opSeq=BAP,APL,...` requires selecting a **different handoff** for its second patch operation. The P0 design proposes an optional `handoffSeq=<path1>,<path2>,...` parameter: successive handoffs are consumed by patch-applying steps (`BAP` or `APL`); subsequent `CHK/CMT/PSH/PR` use the most recently selected handoff.

```bash
apatch.sh opSeq=BAP,APL,CHK,CMT,PSH,PR \
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

## 7. Open decisions

1. Approve `handoffSeq` for multiple different patches in one `opSeq` invocation (or select a different handoff-selection syntax).
2. Approve the reserved `.apatch/created_patches.txt` ZIP metadata member and separate-file bootstrap before support is implemented.
3. Approve strict rejection when a selected patch is missing from an existing created registry, rather than auto-registering it.

Mark this sub-spec `ACCEPTED` only after these choices are resolved. No implementation is authorized by this DRAFT.
