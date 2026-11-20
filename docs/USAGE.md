# Usage

`apatch` applies verified ZIP handoffs to a Git repository and coordinates local checks, commits and guarded GitHub publication. Install it as described in [Installation](INSTALLATION.md). Run the CLI **from the target repository root**, not from the tool checkout.

## First patch and continuation

A new ZIP contains `<repository>/.apatch/params.json` with schema version, repository name, feature branch, ZIP basename and complete commit message. Optional fields include a verified base commit and `delete_paths`; the ZIP must not embed its own SHA-256. `apatch` validates the archive and caches the verified handoff in the target's ignored `.apatch/params.json`. Explicit legacy JSON handoffs remain supported.

```bash
apatch my-patch-stem opSeq=APL,BRN,CHK,STS skipApproves=true
apatch opSeq=CMT,PSH,PR,STS skipApproves=true
```

For ZIP-first operation, **`APL` (3) precedes `BRN` (1)**: apply on a clean base, then move pending changes to the feature branch. The deprecated `BAP` (2) is only for explicit legacy JSON. `skipApproves=true` suppresses prompts, not integrity checks. Omitting the handoff on later commands uses the verified project cache; it never selects an arbitrary recent download.

For another **new ZIP** in the same feature branch, supply that ZIP and explicitly request LOOSE continuation without `BRN`:

```bash
apatch next-patch-stem opSeq=APL,CHK,STS followup=true skipApproves=true
```

`followup=true` checks existing branch and applied history, including committed/published predecessors where supported. It does not replay the old archive. Multiple distinct ZIPs in one invocation use `handoffSeq=` with a matching number of `APL` steps, subject to the LOOSE-only sequence rules.

## Modes and actions

| Mode | Meaning |
| --- | --- |
| `LOOSE` (default) | Manual edits, several ZIPs per commit and deferred push, with safety checks |
| `--strict` | Enforced phase/branch ordering and verification |
| `--force` | Deliberate reconciliation of external changes; **never force push** |

| ID | Code | Operation |
| ---: | --- | --- |
| 0 | `EXT` | Exit |
| 1 | `BRN` | Create/prepare feature branch; ZIP-first transfer |
| 2 | `BAP` | Legacy JSON branch + apply (deprecated) |
| 3 | `APL` | Validate and apply ZIP |
| 4 | `CHK` | Run canonical project checks |
| 5 | `CMT` | Create local commit |
| 6 | `PSH` | Non-force push |
| 7 | `PR` | Create or verify a matching pull request |
| 8 | `MRG` | Guarded merge after PR/review/CI checks |
| 9 | `SYN` | Synchronize local base branch |
| 10 | `STS` | Read-only patch status |
| 11 | `AUD` | Read-only repository audit |
| 12 | `FMT` | Optional configured formatting |
| 13 | `REV` | Optional configured independent review |
| 14 | `BLD` | Optional build without tests (when the BLD increment is installed) |

Action numbers are stable. Use `op=CODE` for one action or `opSeq=A,B,...` for an explicit ordered sequence; execution stops on an error or an unsafe no-op. `STS` can diagnose an unfinished workflow without modifying Git. `AUD` is offline by default; `verifyRemote=true` explicitly adds bounded GitHub reads. `info=PROGRESS` shows installed-tool-wide recorded activity without selecting a target repository.

```bash
apatch op=STS
apatch op=AUD
apatch op=AUD verifyRemote=true
apatch info=PROGRESS
```

## Build, checks and review

The target's `.apatch/config.yaml` is the source of project-specific commands. Example (choose commands valid for your project):

```yaml
schema_version: 1
checks:
  - ["sh", "./run_tests.sh"]
format_commands:
  - ["python3", "-m", "ruff", "format", "--check", "."]
build_commands:
  - ["sh", "./build.sh"]
review_required: false
```

`BLD` runs only `build_commands`, without executing `checks`; it is optional and does not count as `CHK`. `FMT` requires `format_commands`. A successful `CHK` is tied to checked bytes and policy; editing source, staging different content or changing policy invalidates its evidence. `REV` runs only explicitly configured script/model providers, after `CHK`. Set `review_required: true` to enforce a fresh passing independent review before committing where the applicable workflow requires it. Reviewer processes run with the user's permissions; configured external model tools may disclose supplied input.

Where the deferred-check increment is installed, the project may choose a later compulsory canonical-check gate:

```yaml
disabled_without_chk: MRG
```

Allowed values are `CMT` (default), `PSH`, `PR` and `MRG`. An explicit LOOSE invocation may use `disabledWithoutChk=MRG`. This does **not** waive `CHK` at or before the configured gate, any separately stricter `STRICT`/guarded-goal rules, review/CI or GitHub merge restrictions. The final gate requires verification matching the exact final commit revision. Do not treat `BLD` as equivalent to testing.

Reviewer evidence is private runtime data under `.apatch/reviews/`. Opt-in `review_artifacts_enabled` records bounded raw streams; `review_artifact_max_bytes` limits captured bytes. Structured scanner adapters, bounded summary context and selective evidence retrieval are internal APIs, not public CLI operations. Content disclosure uses explicit `review_context_external_consent`; enabling `review_context_include_messages` or `review_context_include_diff` requires that consent. Retention remains disabled by default unless `review_retention_enabled` is set with bounded `review_retention_max_runs`, `review_retention_max_bytes` and `review_retention_max_age_days`. Export is metadata-only and explicitly consented; evidence files can contain secrets and must not be committed.

## Guarded goals and macros

In LOOSE, `goal=CHECKED|COMMITTED|PUSHED|PR_CREATED|MERGED` computes guarded steps from verified local/remote evidence instead of replaying a fixed sequence. `planOnly=true` previews without Git or state writes. `intent=new|continue|auto` resolves the intended feature session. Guarded goals refuse unknown manual/staged paths, even with unattended approvals.

```bash
apatch my-patch-stem goal=CHECKED planOnly=true
apatch my-patch-stem goal=COMMITTED skipApproves=true
apatch goal=MERGED planOnly=true
```

Named LOOSE macros `op=APPLY_PATCH`, `op=APPLY_PATCH_CHECK`, `op=MERGE` and `op=RUN_ALL` use the guarded planner; their remote operations are not implied by `skipApproves=true` alone. `MERGE` resumes an already applied session; `RUN_ALL` may start a new handoff. An uncertain remote operation must first be reconciled read-only.

## Safety and recovery

- **New feature branches:** all modes check for unfinished local/remote feature work and open PRs. Unverifiable GitHub/remote state blocks creating another branch. A verified already applied ZIP may instead be continued on its existing branch.
- **Dirty worktree:** manual changes are preserved, not reset. ZIP overwrites and explicit `delete_paths` are validated; paths under `.git`, unsafe links and traversal are rejected. Review the actual ZIP and staged changes before unattended publication.
- **Interrupted `APL`:** inspect `git status`, `apatch op=STS`, `.apatch/backups/` and the local operation journal. Never automatically rerun archive extraction when `APL` was recorded successful. An explicitly reselected matching ZIP can resume only after digest, history, checkpoint and live Git evidence agree.
- **Failed `BRN` after ZIP-first `APL`:** keep the unchanged base HEAD and pending patch bytes. If the planned feature name conflicts, use `apatch op=BRN featureBranch=feature/unused-name skipApproves=true` only after verifying the documented reassignment preconditions.
- **Uncertain PR/merge or failed `SYN`:** query the exact PR, head SHA and merge status before retry. A confirmed merge may be followed by a separate `SYN`; do not create a duplicate PR or force-push.
- **Failed or timed-out `CHK`/`REV`:** preserve edits and inspect console diagnostics. `CHK` runs project-defined executable commands and may affect the repository; it does not automatically run every optional suite in the `apatch` checkout.

State, registry and operation journals are records, not proof that an external GitHub action completed. For detailed security ownership and recoverability, see [Architecture](ARCHITECTURE.md#security-and-recovery). For exact option grammar, run `apatch --help`.
