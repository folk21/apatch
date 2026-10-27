# APATCH-SUB-003 — Feature Sessions and Context-Aware Execution

**Status:** DRAFT (GENSPEC). FS-00 checkpoint-linkage correction and FS-00R deterministic ZIP resume are present in the inspected source; FS-01–FS-06 context-aware behavior remains proposed. Implementation evidence does not constitute final developer acceptance.

**Parent:** [APATCH-SPEC-001](../spec-apatch-orchestrator.md). **Implementation plan:** [APATCH-PLAN-003](../../plans/feature-session-context-aware-implementation-plan.md).

## 1. Purpose and boundaries

The orchestrator SHALL be able to resume a feature branch across independently supplied ZIP patches, manual edits, canonical-check failures, commits, pushes, and pull-request updates. It SHALL derive a bounded execution plan from observed evidence and execute only steps whose safety preconditions are proven. This supplements, rather than replaces, the deterministic `op` and `opSeq` interfaces.

The existing `followup=true` implementation is a **narrow legacy continuation mechanism**: LOOSE only, newly selected ZIP, uncommitted predecessor at the same HEAD and remote, exact planned feature branch, and prior dirty worktree. It does not handle committed or pushed predecessors. `handoffSeq` batches several explicitly selected ZIPs in one invocation. Neither is a context-aware planner today.

**Non-goals:** autonomous generation of repair patches; force-push, reset, rebase, GitHub branch deletion, silent conflict resolution, overriding review/CI/branch protections, hidden background polling, cross-repository transactions, arbitrary shell-script planning, or changing the numeric operation IDs. This sub-spec does not authorize `goal=`, `intent=`, or `planOnly=` until an implementation stage is separately approved.

## 2. Terminology and source of truth

| Term | Contract |
| --- | --- |
| Patch | One immutable, digest-verified ZIP and its embedded schema-v1 handoff, identified by its exact basename and digest. |
| Patch workflow | Existing per-patch state/history entry; records the attempts and facts about that ZIP. |
| Explicit ZIP selection | A supplied ZIP name or basename selects an archive for a new `APL` **or** identifies an already-applied workflow for later operations. Selection alone is never a request to extract files. |
| Feature Session | Durable association of a repository, configured remote/base, intended feature branch, one or more patches, manual work and publication revisions, ending only after verified completion or explicit abandonment. |
| Execution | One attempt to run an action or a bounded plan, with stable operation-run and progress correlation IDs. |
| Goal | Explicit requested terminal state, not an instruction to disregard intermediate guards. |
| Reconciliation | Read-only comparison of journal/checkpoint claims with current local Git and, when necessary, bounded remote GitHub evidence. |
| Commit scope | The exact current staged/unstaged/untracked paths whose content is authorized to enter a commit. |

Authoritative **current** facts come from Git worktree/index/refs, and live remote refs/PR/review/CI data when publication is involved. The per-target state, applied and created patch registries, operation journal, and tool-wide progress contain **recorded evidence**, not independent proof of current external state. Text logs are diagnostics, never a decision authority. The new planner SHALL use `VERIFIED`, `RECORDED`, `UNKNOWN`, and `CONFLICT` evidence labels consistently with SUB-001 and SUB-002.

An offline plan MAY contain local steps, but SHALL NOT assert that remote publication is already safe or completed when remote evidence is unknown. Remote unavailability SHALL prevent execution of remote-dependent steps.

## 3. Session identity and persistence

1. A new session SHALL have a stable opaque `session_id` and verified repository-root, remote-identity, base-branch and feature-branch associations. Branch name alone SHALL NOT define session identity: the same branch name can be reused after a previous PR was merged.
2. Each patch workflow MAY reference a `session_id`; one session MAY reference multiple patch workflows, commits, and historical PR revisions. A later patch does not supersede an earlier successfully applied patch merely because it becomes the cached handoff.
3. The current implementation caches the last successfully applied ZIP handoff in `.apatch/params.json`. A future verified explicit selection of an already-applied ZIP MAY atomically change the cached **active selection** without recording a new application; this distinction SHALL be visible in state/progress. The cache SHALL NOT be promoted to the session's source of truth or be confused with the most recently applied ZIP. Existing `.apatch/apply_patch.state.json`, `applied_patches.txt`, optional `created_patches.txt`, and operation runs SHALL remain valid. A future schema migration MUST preserve every prior record and unknown compatible fields; no destructive normalization is permitted.
4. Session creation/adoption SHALL be explicit or uniquely inferred from verified local and remote facts. Multiple candidate sessions, divergent repository remotes, detached HEAD, stale commit/PR association, or conflicting ancestry SHALL yield `AMBIGUOUS` or `BLOCKED`, not an arbitrary selection.
5. Previous checkpoints SHALL NOT be marked `superseded` before the replacing application succeeds. For accumulated patches, record an additive session relationship instead. Legacy `superseded_by` keys remain readable as historical selection records, not proof that earlier bytes were removed or their work abandoned.
6. All session and execution metadata writes SHALL use the existing project-local locking and atomic-write patterns; an interrupted attempt SHALL remain reconstructible from immutable history and live evidence.

## 4. Proposed CLI contract

Existing `op=<code>`, `opSeq=<codes>`, `handoffSeq=<zip,...>`, `followup=true`, `skipApproves`, and LOOSE/STRICT/FORCE invocations remain supported. `opSeq` SHALL remain an exact user-supplied imperative sequence and SHALL NOT silently skip or reorder its actions.

The proposed higher-level form is:

```bash
apatch.sh <new-zip-stem> goal=MERGED skipApproves=true
apatch.sh <new-zip-stem> intent=continue goal=MERGED
apatch.sh goal=MERGED
apatch.sh <new-zip-stem> goal=MERGED planOnly=true
```

All examples in this section are **proposed syntax, not installed CLI functionality**.

- `goal=CHECKED|COMMITTED|PUSHED|PR_CREATED|MERGED` expresses an explicit target. `MERGED` includes a verified GitHub merge **and** successful local base synchronization (`SYN`); intermediate goals stop without unrequested publication.
- `intent=auto|new|continue` defaults to `auto`. `auto` chooses only a uniquely verified scenario; `new` demands the base-to-feature lifecycle; `continue` demands a verified existing unfinished session on the intended feature branch. Intent NEVER overrides branch, remote, ZIP, CI, review, or commit-scope protections.
- Selecting a new ZIP always requires its explicit basename or validated path. Omitting the ZIP resumes a unique cached or persisted session without reapplying the archive. Unknown or ambiguous sessions require explicit selection.
- `planOnly=true` runs non-mutating reconciliation and shows the proposed operations, evidence, blockers and required permissions. It MUST NOT create locks, state, progress entries, commits, PRs or Git ref changes. Explicit optional remote inspection is read-only and bounded.
- The initial high-level implementation SHALL support LOOSE only. STRICT/FORCE continue to use existing explicit operations until their separately specified adaptation is verified.
- `goal` SHALL be mutually exclusive with `op` and `opSeq`. Legacy `followup=true` remains usable for its current documented narrow case. Its removal, repurposing or implicit acceptance by `goal` requires a separate compatible migration and regression coverage.

### 4.1 Explicit ZIP selection during deterministic continuation

The **proposed** compatibility enhancement SHALL also apply to existing `op=` and `opSeq=` calls, independently of whether the higher-level `goal` planner is enabled:

```bash
apatch.sh <already-applied-zip-stem> opSeq=CHK,CMT,PSH,PR,MRG,SYN,STS skipApproves=true
apatch.sh <already-applied-followup-zip-stem> opSeq=CHK,STS skipApproves=true
apatch.sh <already-applied-zip-stem> op=CHK
```

These examples are **requirements, not claims about the installed CLI**. The supplied ZIP SHALL identify the workflow being continued, even if `.apatch/params.json` currently refers to a different ZIP. A successful prior `APL` followed by a failed `CHK` SHALL NOT force omission of the ZIP argument. `BRN` may be pending only for the original ZIP-first `APL` on the configured base branch; a follow-up ZIP already applied on the active feature branch SHALL NOT trigger a second `BRN`.

1. The CLI SHALL distinguish **new archive**, **already-applied matching archive**, and **unknown/conflicting archive** before it executes a lifecycle action. A positional ZIP and a leading `APL` initiate application **only when the archive is new**; a matching previously applied ZIP is handled under the verified idempotent-step rule in §4.2. A positional ZIP and a leading `CHK`/later operation mean selection and continuation, **never implicit reapplication**. Deliberate archive reapplication remains a separately confirmed interactive action. Exact `opSeq` order SHALL be preserved: every requested step is evaluated and accounted for, even when its effect is already satisfied.
2. A matching selection SHALL require an unambiguous repository, ZIP basename, recorded handoff metadata/signature and SHA-256, completed application evidence in the workflow checkpoint and applied-patch history, and a consistent feature-session/branch association. Cross-check the operation journal, current Git branch/HEAD/remote, and patch ordering wherever those facts affect the requested next action. A recorded phase or `zip_first=true` alone SHALL NOT establish prior application. In particular, **both** an initial ZIP applied on the base and a distinct follow-up ZIP applied directly on a feature branch SHALL be eligible when independently verified.
3. A supplied archive that still exists SHALL be revalidated against the recorded digest and safe embedded metadata. If the archive is absent but durable, previously verified handoff metadata and the applied history uniquely identify it, the resolver MAY offer a recorded-identity-only continuation with an explicit reduced-evidence label; it SHALL NOT silently reconstruct bytes, claim fresh archive verification, or allow `APL` without the actual archive. The first implementation MAY require the ZIP file to remain available; its limitation SHALL be stated explicitly.
4. If the selected ZIP belongs to a different current session, has a conflicting SHA-256, missing application history, interrupted `applying` phase, ambiguous duplicate name, or an unverified older `superseded_by` relationship, the CLI SHALL stop **before a write or GitHub mutation**. It SHALL report the conflicting facts and a safe inspection command. Historical `superseded_by` is weak bookkeeping evidence and SHALL NOT automatically prove that an earlier patch is invalid or that its contents were discarded.
5. Successful selection MAY update the ignored cache atomically under the existing lock **after** matching identity is validated; it MUST NOT add a second applied-history entry, re-extract archive members, create a branch, alter the worktree/index, or manufacture successful `APL`/`CHK` events. A failed selection MUST NOT change the cache, state/history or source files. The requested subsequent operations retain their normal independent preconditions.
6. A fresh **different** repair ZIP remains a new `APL`. Compatibility `followup=true` retains its current narrow new-application meaning; it SHALL NOT be required to reselect an already-applied ZIP. If supplied redundantly with a continuation command, the CLI SHALL explain the conflict and show the exact corrected command. `handoffSeq` remains the explicit mechanism for multiple **new** APL operations in one sequence.
7. In LOOSE mode, developer edits, formatter-produced changes and independently repaired check scripts SHALL remain intact during reselection and repeated `CHK`. `skipApproves=true` cannot convert a selection into archive overwrite or authorize an unsafe commit. A wrong checkout/HEAD, stale validation or unknown commit scope SHALL be reported before an unattended commit/push/merge, with the branch transition or recheck required to proceed.

### 4.2 Verified already-satisfied steps in explicit sequences

When a previously completed `APL` or `BRN` occurs again in `opSeq`, the engine SHALL distinguish a **proven already-satisfied operation** from an ordinary `NO_OP` and from a request to deliberately reapply an archive. A matching step returns `ALREADY_SATISFIED` and execution continues to the next **originally requested** step; no extraction, branch operation, backup, staged change or GitHub mutation is performed for the satisfied step.

For an `APL` to be already satisfied, the selected ZIP MUST be the **last successfully applied ZIP in the active repository Feature Session**, verified by the ordered applied-patch history and matching workflow/checkpoint evidence. Its exact basename, SHA-256, embedded handoff metadata, target repository, branch and session association MUST match the recorded application. A current name match, cached handoff or previous successful phase alone is insufficient. A manually edited or reformatted worktree is not a reason to replay the ZIP; it is reason to require fresh `CHK` before any new commit.

For a `BRN` to be already satisfied, the current checked-out branch MUST be the intended branch for that same verified patch workflow; its recorded branch transition, current HEAD/ancestry and remote identity MUST be consistent. Merely finding a local branch of the requested name SHALL NOT satisfy `BRN`. For a previously applied follow-up ZIP, the branch may have existed before its application; the engine SHALL not attempt to create it again. An initial ZIP still awaiting a genuine branch transition MUST execute `BRN` under its normal guards.

Only a uniquely verified, session-consistent current workflow may use this idempotent path. If the selected ZIP is not the last applied patch, belongs to a different session, has conflicting bytes/metadata, or the checkout/HEAD/remote cannot be reconciled, the command SHALL stop before mutation and explain the discrepancy. `skipApproves=true` SHALL NOT weaken this condition. Intentional interactive `APL` reapplication retains its explicit confirmation and collision protections; the sequence-idempotency rule SHALL NOT silently broaden permission to overwrite developer edits.

An `opSeq` consisting entirely of verified `ALREADY_SATISFIED` steps SHALL complete successfully without changing source, Git refs, applied history or publication state. Within any sequence, `SUCCESS` and `ALREADY_SATISFIED` allow progression, while `ERROR`, `BLOCKED`, `UNKNOWN_REMOTE_RESULT` and an unproven `NO_OP` stop progression. A successful historical `CHK` SHALL NOT be treated as fresh verification when the current bytes, HEAD, branch or verification policy differ; an explicitly listed `CHK` continues to execute its canonical checks.

The engine SHALL show a minimal in-sequence `ALREADY_SATISFIED` line and consolidate all skipped steps in the **final sequence summary**, including operation number/code and independently verified reason. A skipped action is not a new success attempt and SHALL NOT fabricate a repeated application or branch-creation event. Use a low-intensity informational/amber color for satisfied skips; reserve red for actual blocks or errors. The summary SHALL clearly distinguish **executed**, **already satisfied**, and **not executed** actions and state whether source files were preserved.

## 5. Deterministic context classification

The planner SHALL distinguish at least these observed scenarios:

| Context | Expected safe plan prefix | Critical evidence |
| --- | --- | --- |
| New ZIP on clean, synchronized base | `APL,BRN,CHK` | Base HEAD matches remote and branch creation preflight passes |
| New ZIP on active feature with uncommitted predecessor | `APL,CHK` | Same verified session, branch, HEAD, remote; safe overlap resolution |
| New ZIP after earlier committed feature work | `APL,CHK,CMT` | Parent commits and intended branch/remote verified; no unrelated revision or conflict |
| New ZIP after previous push/open PR | `APL,CHK,CMT,PSH,PR` | PR identity, head SHA/base and remote ancestry refreshed after new push |
| Existing ZIP already applied, checks failed | `CHK` | Digest/history indicates application; never replay ZIP |
| Explicit existing ZIP selected while cache names another patch | Resume selected workflow's eligible next action | Unique matching archive/checkpoint/history/session; no accidental cached-patch substitution |
| Existing follow-up ZIP already applied on feature branch | `CHK` or next verified action; no `BRN` | Recorded direct feature-branch application, SHA-256, HEAD/remote and patch ordering |
| Exact last-applied ZIP selected with `opSeq=APL,BRN,CHK` on its already prepared branch | `APL` and `BRN` report `ALREADY_SATISFIED`; execute `CHK` | Last-in-session applied history, exact digest/metadata, current branch and HEAD/remote relationship |
| Exact `opSeq=APL,BRN` repeated with no subsequent actions | Successful summary with both operations already satisfied | No worktree or ref mutation and no manufactured new application or branch evidence |
| `CHK` command executable missing after `APL,BRN` | Stop at `CHK`, then repeat `CHK` after repair | Exact failing configured argv, repository-root resolution, unchanged applied-patch checkpoint |
| Exact current bytes already verified | `CMT` or later | Same worktree/index fingerprint, HEAD, branch, config/check policy revision |
| Commit or push done manually | Reconcile and resume from next step | Actual commit ancestry and remote refs agree with the intended session |
| PR merge outcome uncertain | No remote mutation | Query live matching PR and verify source revision before retry |

The planner SHALL recalculate context and guards **after every completed step**. A phase string, apparent absence of dirty paths, or prior successful run alone is not permission to skip checks. When a step is already satisfied, output `ALREADY_SATISFIED` with evidence rather than conflating it with `NO_OP`. Every satisfied step in deterministic `opSeq` SHALL also preserve its original position and report the evidence; neither interface may silently infer completion.

The existing single-active-feature-branch creation gate remains mandatory. A current checkout on `main` is valid before the initial `APL,BRN`; it is **not** valid for unattended `CMT` or `PSH` of a new feature.

## 6. Manual changes, checks and commit scope

1. Manual changes SHALL be recognized as ordinary input. Disjoint edits MUST be preserved during `APL`; colliding edits MUST be detected before overwriting. Backups alone are not proof that overwriting is authorized.
2. Unattended execution MUST NOT overwrite/delete overlapping user changes solely because `skipApproves=true` was supplied. An ambiguous overlap SHALL stop **before extraction** with the paths and a recoverable decision. A future explicit, narrowly scoped replacement authorization MAY be specified separately.
3. The planner SHALL classify commit candidates into applied-patch changes, explicitly accepted manual changes, pre-existing staged paths, and unclassified paths. Unclassified paths MUST NOT silently enter an unattended `git add -A` commit. Preserve the existing index and unstaged work on a blocked plan.
4. A commit MAY proceed automatically only on the verified intended feature branch, with an explicitly determined scope and fresh canonical-check evidence covering **exactly** the content to commit. The current direct LOOSE `CMT` compatibility behavior remains unchanged until its separate migration is approved.
5. A check that exits zero but modifies tracked or untracked checked bytes SHALL NOT be marked verified on its initial run. The modified bytes remain available; `CHK` can be safely repeated without `APL`. A bounded automatic recheck MAY be enabled only with explicit project policy, deterministic fingerprints, and an upper retry limit; persistent changes stop with an actionable diagnostic.
6. A failed test blocks the dependent commit/publication step. Generating or applying a repair ZIP is an independent explicitly selected operation; the planner does not invent ZIP files.
7. `skipApproves=true` suppresses ordinary prompts only after every applicable invariant passes. It does not approve ambiguous scope, unverified work, wrong branch, overlap deletion, PR drift, CI/review gaps, or remote uncertainty.
8. A missing or unexecutable command configured under `.apatch/config.yaml:checks` SHALL identify the target repository root, the configured command/argv, whether the failure was not-found or permission-denied, and the config path. It SHALL stop the requested sequence before `CMT` and subsequent publication steps. After the user repairs the script or configuration, a new `CHK` SHALL be allowed using either the verified cached selection or the explicit already-applied ZIP, without `APL`/`BRN` replay. A changed check configuration or source fingerprint invalidates prior successful verification evidence.

## 7. Publication, reconciliation and recovery

For unattended publication, require exact Git repository identity, intended feature branch, expected ancestry, verified commit SHA, fast-forward remote update, fresh source SHA/base of the unique matching PR, and project/GitHub review and CI policies. A non-fast-forward remote, an unreviewed changed revision, a closed historical PR, or incomplete live evidence SHALL block or require an explicit reconciliation operation.

An explicit `goal=MERGED` authorizes a guarded PR merge attempt but DOES NOT permit bypassing configured GitHub policies. Read-only GitHub calls may reuse existing bounded retry policy; unknown results from `gh pr create` or `gh pr merge` SHALL NEVER trigger automatic replay. Once a matching merge is conclusively verified, `SYN` is independently retryable and uses fast-forward-only local synchronization.

Each stopped plan SHALL report: current phase, observed branch/HEAD, intended goal, completed and skipped steps, exact blocking fact (with evidence class), unchanged user-owned data, and one safe recovery/resume command. An interruption after a successful step resumes from verifiable evidence; the planner does not roll back GitHub, delete user data or replay a previously applied ZIP.

For deterministic `opSeq` continuation, the recovery command SHALL show the **remaining** actions from the failed step, not repeat `APL` or `BRN` if they were conclusively completed. If a ZIP basename was explicitly supplied, the suggested command SHOULD retain that same basename when it can be safely reselected. Suggestions that include `CMT`, `PSH`, `PR` or `MRG` SHALL visibly disclose external or irreversible effects; an additional short `CHK,STS` alternative SHOULD be shown when independent review is advisable. Commands SHALL be copyable with shell-valid line continuations; the shell's handling of whitespace after `\` occurs before `apatch` starts and is not detectable by the CLI.

## 8. Presentation and machine-readable outcomes

Display a structured `CONTEXT`, `PLAN`, `GUARDS`, `EXECUTION`, and `RECOVERY` summary. Outcome classes SHALL distinguish `SUCCESS`, `ALREADY_SATISFIED`, `NEEDS_VERIFICATION`, `WAITING_FOR_USER`, `BLOCKED`, `ERROR`, and `UNKNOWN_REMOTE_RESULT` in the proposed planner presentation. Map to persisted legacy outcomes without silently changing schema-v2 meanings.

An explicit already-applied ZIP selection SHALL produce a short, structured notice with selected basename, recorded application phase, planned versus observed branch, validated evidence, confirmation that no extraction will occur, and the requested first action. A refused selection SHALL name the failed identity/branch/history guard, state that no source files or Git refs were changed, and provide a usable next command. Do not use a generic "new ZIP must start with APL" error for an already-applied matching handoff. Report `CHK` failure separately from failed archive selection; neither SHALL be represented as an unexplained `NO_OP`.

The terminal summary SHALL aggregate `ALREADY_SATISFIED` steps even when they occurred at the beginning of a longer batch. It SHALL remain visible after later successful steps and identify any unexecuted suffix after an actual blocker. A verified skip is informational, not a warning that causes a nonzero exit status; an unproven skip is prohibited. The presentation SHOULD avoid repeated long diagnostics at each satisfied step while maintaining concise per-step progress feedback.

Color capable TTYs SHOULD use green for verified success, cyan for plan/next action, yellow for ambiguity, red for blockers and muted text for context. `NO_COLOR`, `TERM=dumb` and redirected output MUST be ANSI-free. Never rely on color alone for meaning. Preserve bounded error logs and do not expose secrets, test streams or untrusted terminal escape sequences.

## 9. Acceptance criteria

| ID | Observable scenario |
| --- | --- |
| FS-01 | A clean synchronized base and one new ZIP reach `MERGED` through `APL,BRN,CHK,CMT,PSH,PR,MRG,SYN` after all guards pass. |
| FS-02 | On an already correct feature branch, `BRN` is omitted with verified reason; no second feature ref is created. |
| FS-03 | A separate new ZIP extends an uncommitted patch on the same branch; both patches retain distinct history and can share one commit. |
| FS-04 | A new ZIP after a prior commit is applied without resetting, losing, or replaying the older changes. |
| FS-05 | A new ZIP after push/open PR requires fresh checks, new commit/push and matching current PR SHA before merge. |
| FS-06 | Repeated invocation after successful `APL` resumes without ZIP reapplication; duplicate checks remain enforced. |
| FS-07 | Canonical checks modify bytes; the initial check does not authorize `CMT`, and a stable second check can verify the new snapshot. |
| FS-08 | Canonical checks fail; no `CMT`, `PSH`, `PR` or `MRG` occurs, and user edits remain intact. |
| FS-09 | Overlapping manual edits without explicit safe authorization stop before source replacement, without recording successful `APL`. |
| FS-10 | Unknown staged/untracked paths stop unattended `CMT`; no incidental `git add -A` stages them. |
| FS-11 | Branch or remote drift before commit/push blocks publication even with `skipApproves=true`. |
| FS-12 | A matching manual commit/push is reconciled; an unmatched manual revision is reported as ambiguous. |
| FS-13 | Unknown remote outcome after PR creation/merge blocks replay; verified recovery resumes without duplicate mutation. |
| FS-14 | Existing branch creation gate, non-fast-forward prohibition, review and CI enforcement are retained in all modes. |
| FS-15 | Legacy `opSeq`, `handoffSeq`, `followup=true`, explicit JSON and `2 [BAP]` behavior remain compatible. |
| FS-16 | Concurrent or interrupted session updates preserve state/journal identities and permit evidence-backed recovery. |
| FS-17 | A rejected or cancelled follow-up does not mark a previous patch superseded; shared session association is additive. |
| FS-18 | `planOnly=true` leaves Git, state/history/registry, cache, progress, logs, locks and the worktree byte-identical. |
| FS-19 | Offline or malformed remote evidence cannot produce a false verified merged state. |
| FS-20 | TTY/no-color output provides unambiguous next steps, skipped steps and blockers without leaking unsafe control sequences. |
| FS-21 | After successful `APL,BRN` and a failing `CHK`, selecting the same ZIP with `opSeq=CHK,CMT,STS` verifies the repaired bytes, commits only after all guards pass, and never invokes `APL`/`BRN` again. |
| FS-22 | Selecting an already-applied follow-up ZIP on its existing feature branch resumes the correct workflow without forcing `BRN`, even when cache metadata names another prior ZIP. |
| FS-23 | An unknown ZIP, changed ZIP SHA-256/metadata, missing or conflicting application history, interrupted extraction, ambiguous workflow, or wrong repository selection fails closed before any source/cache/GitHub mutation. |
| FS-24 | Verified explicit reselection preserves source bytes, developer fixes, Git index and applied-patch ordering; at most the active handoff cache/selection bookkeeping changes, atomically and with distinct non-APL evidence. |
| FS-25 | Explicit ZIP replay via `APL` retains duplicate-application guards; omitting `APL` never extracts files. `followup=true` is not required for already-applied ZIP continuation. |
| FS-26 | A missing `checks` executable reports the exact project-root-relative argv and configuration location; after fixing it, the same ZIP selection reruns `CHK` without affecting the earlier application record. |
| FS-27 | A stale branch/HEAD, different session, or insufficient commit-scope evidence cannot progress into unattended `CMT`, `PSH` or remote operations, even if the ZIP identity matched or `skipApproves=true` was supplied. |
| FS-28 | `opSeq` recovery displays completed/remaining steps, selected ZIP identity, a safe `CHK,STS` alternative and explicit publication effects, with no unrequested step skipping. |
| FS-29 | All explicit resume paths work with one-step `op`, mnemonic/numeric `opSeq` and no ZIP (cached) calls; legacy JSON, STRICT/FORCE preconditions and multiple-new-ZIP `handoffSeq` retain their documented semantics. |
| FS-30 | Repeating `last-applied-ZIP opSeq=APL,BRN,CHK,STS` on its verified active feature branch reports `APL`/`BRN` as `ALREADY_SATISFIED`, runs `CHK`, and continues without extraction, backups or branch creation. |
| FS-31 | Repeating `last-applied-ZIP opSeq=APL,BRN` returns success with a final two-step satisfied summary and no source, index, ref, history or GitHub mutation. |
| FS-32 | A same-named ZIP with different digest, a non-last applied ZIP, different current branch, divergent HEAD/remote or conflicting session cannot be skipped by `skipApproves=true` and stops before writes. |
| FS-33 | A mixed sequence records and prints executed, already satisfied and unexecuted steps separately; `SUCCESS`/proven `ALREADY_SATISFIED` continue, while unproven `NO_OP`, `ERROR`, `BLOCKED` or uncertain remote outcomes stop. |
| FS-34 | A developer edit made after `APL` survives repeating `APL,BRN,CHK`; `CHK` validates current bytes and an intentional interactive reapplication remains separately guarded. |

## 10. Open decisions before implementation

1. Whether the first planner release should expose only `goal=CHECKED` and `goal=COMMITTED` before enabling `MERGED` after its safety tests.
2. Whether a narrowly scoped `commitScope`/overlap authorization option is needed, and its exact CLI/config schema. **Do not** implement a permissive `allowAll` escape hatch.
3. Exact session schema version, stable ID allocation and migration of legacy `superseded_by` without rewriting historical events.
4. Whether automatic stable-format reruns default off and how a project config opts in with a maximum count.
5. Whether later STRICT/FORCE planner support is valuable; it is out of the first implementation.

The [implementation plan](../../plans/feature-session-context-aware-implementation-plan.md) identifies the design gate and incremental code/test work for every criterion.
