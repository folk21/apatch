# APATCH-SUB-004 — Operational Workflows, Activity Dashboard, and Stable Checks

**Status:** DRAFT. WM-01 (read-only activity in `AUD`) and WM-02 (per-project base branch) have implementation candidates; WM-03–WM-06 are proposed and not yet implemented.

**Parent:** [APATCH-SPEC-001](../spec-apatch-orchestrator.md). **Implementation plan:** [APATCH-PLAN-004](../../plans/operational-workflows-implementation-plan.md).

## 1. Scope and existing contracts

This sub-spec reduces the number of developer commands needed to complete or resume a safe patch workflow. It owns four high-level workflow macros, cross-project activity presentation in `11 [AUD]`, project-specific base-branch selection, and bounded recovery from check-produced edits. It complements [SUB-001](subspec-01-workflow-control.md), [SUB-002](subspec-02-state-history-audit.md), and [SUB-003](subspec-03-feature-session-planning.md).

The existing implementation already provides:

- Atomic numbered actions `0..11`, `op`, exact `opSeq`, `handoffSeq`, and `followup=true`.
- Read-only repository `10 [STS]`, read-only repository audit `11 [AUD]`, and read-only, tool-wide `info=PROGRESS` backed by an installation-local event ledger.
- Global `apatch.conf:base_branch` (default `main`); WM-02 adds a candidate project-local override.
- `CHECKS_CHANGED_WORKTREE`, which preserves edited bytes and blocks publication when canonical checks change the worktree.

**Non-goals:** renumbering actions, removing `AUD` or `info=PROGRESS`, making GitHub mutations during status inspection, unsafe Git cleanup, autonomous repair-patch generation, hidden branch switching, bypassing review/CI/protected-branch rules, or changing `STRICT`/`FORCE` semantics without a separately tested migration.

## 2. Cross-project activity in `11 [AUD]`

The read-only `AUD` output SHALL begin with a compact activity dashboard for all projects known to the installed tool's progress master, then retain the complete existing audit of the current target repository. The existing `op=AUD`, `op=11`, `opSeq=AUD`, and interactive `11` forms SHALL remain equivalent. `info=PROGRESS` SHALL remain available outside a Git repository and retain its read-only behavior.

For each known project, the dashboard SHALL distinguish:

1. **Last attempted operation:** exact mnemonic, result and recorded completion time, including failed, cancelled, and indeterminate attempts.
2. **Last successful operation:** the latest recorded `SUCCESS` event, or explicitly `none`.
3. **Recorded phase and identity:** repository root, latest patch, observed branch and recorded workflow phase.
4. **Suggested continuation:** evidence-labelled advisory operation, not a claim of live GitHub state.

The tool-wide event ledger may be incomplete (new installation, independent tool copies, manual Git operations, corrupted progress). The dashboard SHALL label its data `RECORDED`; it SHALL NOT imply current remote PR/merge state or discover arbitrary directories. Progress lookup MUST NOT create or repair a file. If the optional progress master is unavailable or unsafe, `AUD` SHALL show a bounded warning and continue its independent repository audit. Malformed repository audit inputs MUST still fail closed. `verifyRemote=true` continues to apply only to the current repository's audit; it does not initiate cross-project GitHub scans.

**WM-01 implementation candidate:** append the dashboard to every `AUD` dispatch path and distinguish the latest attempted versus last successful event in `render_progress()`. This change SHALL be additive and read-only for both the target repository and the tool-wide ledger.

## 3. Four higher-level operations

Introduce the following **proposed** named macro operations without assigning new numeric action IDs. They SHALL be available as `op=RUN_ALL`, `op=APPLY_PATCH`, `op=APPLY_PATCH_CHECK`, and `op=MERGE`. The current `op=MRG` remains the single existing PR merge action. These macro names are not implemented by WM-01.

| Macro | Requested terminal state | Candidate atomic operations |
| --- | --- | --- |
| `APPLY_PATCH` | Selected ZIP safely applied on the intended feature branch | `APL`, `BRN` if actually needed |
| `APPLY_PATCH_CHECK` | `APPLY_PATCH` plus verified stable checked bytes | `APL`, `BRN` if needed, `CHK` |
| `MERGE` | Verified commit published, PR merged and local configured base synchronized | Reverify/`CHK` if needed, `CMT`, `PSH`, `PR`, `MRG`, `SYN` |
| `RUN_ALL` | Complete lifecycle for the selected ZIP or uniquely identified unfinished feature | Application, verification, publication and synchronization operations above |

Every macro SHALL finish with a **best-effort read-only `10 [STS]` report**, whether it succeeded, stopped safely, was cancelled, or received an unknown remote result. Status failure SHALL be reported separately and MUST NOT replace the original failure/exit code. `STS` SHALL NOT be inserted into deterministic `opSeq` through hidden rewriting; macros use their own final-report behavior.

Macro execution SHALL use SUB-003's evidence-based context reconciliation and Feature Session identity, **not** a blind expansion to fixed `opSeq`. A selected archive already applied in the current uniquely verified session SHALL NOT be replayed. An existing matching feature branch SHALL be reused only after verifying its identity, HEAD/ancestry and remote. If a new branch is appropriate, preserve the current safe ZIP-first `APL` then `BRN` order. Manual edits SHALL remain intact. Existing commits or PRs SHALL be reused only when their exact revisions are proven; ambiguous evidence SHALL block mutation with actionable diagnostics. A previously merged feature session does not turn a new ZIP on `main` into `followup=true`.

`MERGE` and `RUN_ALL` SHALL require current verified check evidence for the exact commit scope and SHALL respect the existing GitHub review, CI, PR identity, mergeability, timeout, and fast-forward protections. An unknown result from a GitHub-mutating operation SHALL stop immediately; no automatic duplicate PR creation, merge retry, or speculative synchronization is permitted. `skipApproves=true` skips only existing confirmation prompts; it does not weaken any guard.

Macros SHALL initially support LOOSE only. In `STRICT` and `FORCE`, report their unsupported macro scope with a suggestion to use existing atomic operations. The existing numeric operations, exact `opSeq`, and legacy handoffs remain unchanged. A macro requiring a new ZIP SHALL demand an explicit ZIP identity; continuing without an argument requires one uniquely verified active workflow.

## 4. Per-project base branch

`apatch.conf:base_branch` remains the installation-wide default. Introduce optional project-local `.apatch/config.yaml:base_branch` (schema-v1 YAML) as an explicit override:

```yaml
schema_version: 1
base_branch: develop
checks:
  - ["./run-tests.sh"]
```

Precedence is **project YAML override → global INI value → `main`**. Validate a real Git branch-name value before use and report its configuration source. A missing or malformed override MUST NOT silently fall back to another branch. Apply the effective base consistently to branch creation guards, PR target identity, sync, progress/status messages and publication reconciliation. Existing project configs without this key remain valid. No operation may infer a substitute branch from a GitHub default if an explicit configured target is missing or divergent.

## 5. Stable checks and bounded recovery

Canonical checks SHALL continue to prove the **final** worktree/index bytes, not merely that every command exited zero. The current `CHECKS_CHANGED_WORKTREE` stop remains the backward-compatible default for direct `CHK`.

The future macro execution policy MAY provide opt-in project configuration for:

- `prepare_checks`: bounded argv commands allowed to normalize source (such as formatters) before verification. They are explicit executable code and must be subject to the same timeout and trust warnings as canonical checks.
- `check_worktree_policy: stop|recheck_once`: `stop` is the default. `recheck_once` permits **one** full repeat of canonical checks only when every initial check succeeded but source/index bytes changed during the check run.

After any preparation or changed-worktree run, the old successful-check evidence is invalid. The repeat SHALL start from a fresh fingerprint and re-run the **complete** configured verification list, with no implicit source rollback or ZIP replay. If a repeated run still changes bytes, fails, times out, or encounters unclassified concurrent developer edits, it stops with preserved content and a clear explanation. Successful verification requires identical before/after fingerprints on the **final** run, plus the current branch, HEAD and check-policy identity.

The console SHALL identify the exact changed paths and whether an index entry, status code, symlink target, executable bit or file bytes changed; it SHALL NOT assert that the checks themselves caused the change when a concurrent editor may have done so. No full test output is copied to application logs. The status report SHOULD show a compact warning in amber, a confirmed success in green and a genuine blocker in red, respecting non-TTY output and `NO_COLOR`.

## 5.1 Future bounded GitHub transport recovery (WM-06; deferred)

GitHub API timeouts and gateway failures, including HTTP 504 from `gh pr create`
preflight GraphQL queries, SHALL receive bounded, visible recovery **without
blindly repeating an operation that may have mutated the remote**. This is a
future implementation stage, not a currently available CLI capability.

1. Explicitly read-only GitHub requests MAY be retried on classified transient
   transport errors (network timeout, connection reset, temporary DNS failure,
   HTTP 502/503/504). The implementation SHALL bound **both** total attempts
   and total elapsed time, including lookup, subprocess startup, backoff and
   recovery. An individual subprocess retains the existing
   `github_timeout_seconds` cap. Authentication/authorization failures,
   malformed remote identity, invalid CLI arguments, protected-branch errors,
   failed CI and missing approvals SHALL NOT be retried as transport errors.
2. `gh pr create`, `gh pr merge` and other potentially mutating remote
   operations SHALL NOT be automatically replayed after an indeterminate
   return, including an HTTP 504 originating in GitHub CLI's preflight. The
   orchestrator MAY perform bounded **read-only reconciliation** of the exact
   repository, target/base, feature head and recorded source commit SHA.
   A uniquely matching current PR or verified merge of the exact revision MAY
   be adopted and execution resumed; absent, stale, mismatched or ambiguous
   evidence remains `UNKNOWN_REMOTE_RESULT`. A failed lookup does not prove
   that a PR was not created.
3. Each attempt SHALL print a concise, flushed message showing the operation,
   attempt number/limit, per-call timeout and remaining total time budget.
   On a transient failure, print the error category and bounded backoff with
   the next planned attempt. Long individual requests SHOULD display a
   periodic non-spinning progress/heartbeat notice so an active `gh` process
   cannot look silently hung. The message SHALL not reveal tokens, PR body,
   untrusted terminal sequences or full authenticated command arguments.
4. The bounded defaults SHALL preserve the current single extra attempt for
   read-only calls unless explicitly changed. The next implementation SHALL
   define and validate the maximum read attempts, total recovery budget and
   maximum delay in global/project configuration. Exhaustion SHALL stop
   promptly with a concise history of attempts and a concrete safe `STS`/PR
   inspection command. `skipApproves=true` SHALL NOT override time limits or
   authorize duplicate mutations. `NO_COLOR`, non-TTY and interruption
   handling remain supported.
5. Remote reconciliation SHALL never fabricate a confirmed PR creation,
   successful merge, synchronized local base, or completed macro merely to
   bypass an outage. No hidden daemon/background polling is allowed.

## 6. Outcomes, recovery and compatibility

1. Macro outcomes distinguish `SUCCESS`, verified `ALREADY_SATISFIED`, `BLOCKED`, `CANCELLED`, and `UNKNOWN_REMOTE_RESULT`. Only verified satisfaction may skip a step; ordinary `NO_OP` does not imply successful completion.
2. The console reports which atomic operations executed, which were already satisfied, why any were skipped or blocked, and the next safe action. The final `STS` is clearly a **status report**, not proof that the failed macro succeeded.
3. There is no automatic user-worktree cleanup, destructive Git reset, force-push or abandoned-state normalization. Intentional edits, previous applied ZIPs and pending commits remain recoverable.
4. Global history and project-local state remain separate: only project-local evidence, current Git, and verified remote facts authorize changes. Cross-project activity is advisory and never drives GitHub operations.
5. Existing help, configuration, journal schema, cache, handoffs, `AUD` coverage and standalone `info=PROGRESS` remain compatible. New properties are optional and default to present behavior.

## 7. Acceptance criteria

| ID | Observable requirement |
| --- | --- |
| WM-01 | `op=11`, `op=AUD`, singleton `opSeq=AUD`, and interactive 11 show global recorded activity **and** unchanged target-repository audit; neither report modifies source, Git, progress or project state. |
| WM-02 | Two projects with interleaved `SUCCESS` and `FAILED` events show distinct last attempted and last successful operations; missing progress does not invent earlier activity. |
| WM-03 | Invalid or symlinked progress yields a bounded warning without suppressing a valid repository audit; malformed target audit inputs still fail. |
| WM-04 | Project-local `base_branch` overrides global `main`; omitted setting retains global behavior; invalid/ambiguous branch names and absent remote targets block unsafe publication. |
| WM-05 | `APPLY_PATCH` starts on a clean configured base by applying ZIP before branch creation; already satisfied matching steps are reverified without extraction or new branch mutation. |
| WM-06 | `APPLY_PATCH_CHECK` verifies final bytes; manual edits are preserved and changed-worktree outcomes are not mislabelled as passing checks. |
| WM-07 | Every macro attempts a final `STS` even after a local failure; its result never replaces the original failure/exit code. |
| WM-08 | `MERGE` resumes an exact verified unfinished workflow, requires current checked commit scope, and does not replay previously confirmed commit/push/PR/merge operations. |
| WM-09 | `RUN_ALL` reaches verified sync only when all local and live remote gates pass; an uncertain PR mutation stops without repetition. |
| WM-10 | New ZIP on a clean configured base after a merged prior session starts a new branch; `followup=true` is not invented. |
| WM-11 | `STRICT`/`FORCE` and all numeric `0..11` operations retain prior semantics; new macros fail explicitly until supported. |
| WM-12 | `check_worktree_policy=stop` remains the default; `recheck_once` performs at most one full verification rerun after all first-pass checks succeed but bytes change. |
| WM-13 | Formatter convergence verifies stable final bytes; repeated changes, failed checks, timeouts and simultaneous manual edits remain blocking with preserved files. |
| WM-14 | Diagnostics identify changed paths and differences without inventing the modifying process; secrets/full check output are not logged. |
| WM-15 | Empty or malformed optional history never authorizes GitHub actions, and complete success is distinguishable from recorded-only status. |
| WM-16 | Terminal colors are appropriate and suppressed for non-TTY or `NO_COLOR`; stdout/stderr and exit codes remain machine-usable. |
| WM-17 | Two transient read failures followed by a successful read show bounded, numbered progress; a permanent 401/403, CI failure or invalid request gets no automatic retry. |
| WM-18 | Lost acknowledgement or HTTP 504 during PR creation triggers only read-only reconciliation; a unique PR with matching repo/base/head/source SHA is adopted without a second create. |
| WM-19 | No matching PR, multiple matches, stale source SHA or exhausted lookup budget produces `UNKNOWN_REMOTE_RESULT`, preserves checkpoint identity and never issues another remote mutation. |
| WM-20 | An uncertain merge is adopted only with live proof of the exact PR and revision; network errors do not authorize merge, sync or review/CI bypass. |
| WM-21 | Per-request timeout and whole-operation time budget are enforced; attempt and heartbeat messages remain bounded, flushed, redacted and understandable with `NO_COLOR`/redirected output. |

## 8. Delivery status

- **WM-01:** implementation candidate with focused tests in the associated source patch; not marked released until integrated and independently verified.
- **WM-02:** implementation candidate with Git-syntax validation, source-labelled effective base and focused project/branch/PR tests; not marked released until integrated and independently verified.
- **WM-03–WM-05:** advisory implementation stages only. No new macro CLI or automatic check rerun is claimed as installed.
- **WM-06:** deferred GitHub transient-read retry and safe mutation-result reconciliation design. The current single extra read-only retry remains the installed behavior; no new mutation retry or automatic recovery is claimed.
