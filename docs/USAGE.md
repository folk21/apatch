---
type: Usage Guide
title: Using apatch
description: Operational CLI guide with commands, examples, safety checks, recovery, and publication flows.
---
# Using apatch

`apatch` is a Git/GitHub CLI for consuming verified ZIP patch handoffs, running
project-defined checks, and publishing changes behind safety gates. It also has
**producer** tools for building ZIPs from a separate source checkout. This
is an operator guide: it describes decisions, commands, and recovery, not the
internal Python implementation.

**Start here:** [Installation](INSTALLATION.md) explains the deployed CLI and
its global configuration; [Architecture](ARCHITECTURE.md) describes module
ownership, security and development checks. Run `apatch --help` for the exact
syntax supported by your installed version. **Always execute consumer
commands from the target Git repository root**, not the installation folder.

## At a glance

| Goal | Example | What it does |
| --- | --- | --- |
| Inspect the selected patch | `apatch op=STS` | Read local workflow evidence; does not query GitHub |
| Audit the repository | `apatch op=AUD` | Read-only local patch-history reconciliation |
| Apply a first ZIP | `apatch first-patch opSeq=APL,BRN,CHK,STS skipApproves=true` | Extract on the base branch, transfer changes to the feature branch, run checks |
| Continue after checks | `apatch opSeq=CMT,PSH,PR,STS skipApproves=true` | Commit, push and create/verify a PR; does not merge |
| Add another ZIP | `apatch next-patch opSeq=APL,CHK,STS followup=true skipApproves=true` | Continue an eligible LOOSE feature session; no second BRN |
| Examine an execution plan | `apatch first-patch goal=CHECKED planOnly=true` | Read-only guarded plan, without performing the steps |
| Inspect tool-wide progress | `apatch info=PROGRESS` | View recorded activity without selecting a target repository |

**Publication is opt-in.** `PSH`, `PR`, `MRG` and some named macros/goals can
change GitHub state. `skipApproves=true` removes interactive confirmations,
**never** ZIP, Git, approval, CI, review, or other safety checks. Review source
content and staged changes before choosing unattended publication.

## 1. Prepare a target repository

Before using a patch, verify:

1. The target has the correct Git `main` (or configured base), clean worktree,
   expected Git remote, and no conflicting unfinished feature work.
2. The deployed CLI is recent enough to understand the ZIP metadata and the
   operations you intend to use. A newer development checkout is **not** proof
   that the installed CLI includes its features.
3. The target's tracked `.apatch/config.yaml` defines at least one real,
   canonical `checks` command. These commands run from the target root.
4. The patch ZIP is in the configured global `downloads_dir` (normally
   `~/Downloads`), outside the Git worktree. The filename supplied to
   `apatch` is a ZIP stem or basename, not an arbitrary folder name.

Example project configuration (replace the scripts with scripts **your**
project actually has):

```yaml
schema_version: 1
checks:
  - ["sh", "./run_tests.sh"]
format_commands:
  - ["sh", "./format_project.sh"]
build_commands:
  - ["sh", "./build_project.sh"]
check_timeout_seconds: 900
check_idle_timeout_seconds: 30
```

The `checks` list is required; other fields are optional and their associated
operations cannot run without configured commands. A command is an explicit
argument vector: there is **no implicit shell**, variable expansion, pipes,
redirection, or glob expansion. Invoke `sh` or a checked-in project script
explicitly when shell features are needed. Never put a mutating formatter in
`checks`.

Global defaults use an **INI** file named `apatch.conf` at the installation
location (the standalone deployment preserves its own configuration):

```ini
[apatch]
downloads_dir = ~/Downloads
base_branch = main
github_timeout_seconds = 30
github_ci_wait_seconds = 300
check_timeout_seconds = 900
check_idle_timeout_seconds = 30
```

Project YAML can override supported global options; it does not accept
arbitrary new keys. In particular, proposed SDD `run_types`, `rtype=DEVELOP`
and `rtype=ACCEPT` are **not** CLI features yet: do not add them to project
configuration until the installed implementation supports them. Do not put
credentials or secrets in tracked config.

## 2. Understand the handoff ZIP

A self-contained ZIP has paths rooted at the **exact target repository name**:

```text
my-project/
  .apatch/params.json
  src/example.py
  tests/test_example.py
```

The reserved `my-project/.apatch/params.json` contains schema-v1 identity,
the exact ZIP filename, a proposed `feature_branch`, and a complete commit
message. It may also contain verified `base_commit` and `delete_paths`.
`patch_sha256` must **not** be embedded in the ZIP (that would be
self-referential); the consumer calculates and verifies its digest separately.
A companion JSON file is not required. Explicit legacy JSON handoffs remain
available for older workflows; do not combine legacy BAP instructions with a
new ZIP-first handoff.

Before changing any repository files, `apatch` checks archive root confinement,
regular member types, size limits, traversal, symlink hazards, duplicate paths,
metadata consistency, and deletions. `delete_paths` is **not** a suggestion:
each named file must exist and be Git-tracked. If a deletion target was removed
in a newer `main`, the producer must rebase the patch; do not use FORCE to
ignore the mismatch. The same applies when the ZIP was generated from an older
repository snapshot. `apatch` does not perform a Git merge of patch contents.

An accepted handoff is cached in the target's ignored `.apatch/params.json`.
Later commands without an explicit ZIP use this *verified* cache; they do not
select whichever download happens to be newest. Runtime state, applied-patch
history, private backups, review artifacts, and logs belong under the target's
`.apatch/`, not in committed source. The optional created-patch registry, if
supplied, must preserve its real historical order.

## 3. First ZIP: APL before BRN

For a new self-contained ZIP, **apply first on the clean base** (`3 [APL]`),
then **transfer the pending uncommitted changes** to the feature branch
(`1 [BRN]`). This order is intentionally different from legacy JSON `2 [BAP]`.

```bash
apatch my-project-PATCH-new-feature opSeq=APL,BRN,CHK,STS skipApproves=true
```

You can perform these steps separately when you want to inspect changes:

```bash
apatch my-project-PATCH-new-feature op=APL skipApproves=true
apatch op=STS
apatch op=BRN skipApproves=true
apatch op=CHK skipApproves=true
apatch op=STS
```

After `APL` but before `BRN`, the worktree should contain the intended pending
patch bytes on the unchanged base HEAD. `BRN` validates that snapshot and
remote/branch identity before moving them to the feature branch. Do **not**
commit on the base to work around a failed BRN. If the ZIP's suggested branch
name conflicts, a supported LOOSE recovery path can select another one:

```bash
apatch op=BRN featureBranch=feature/unused-name skipApproves=true
```

This requires a verified, still-pending ZIP-first handoff and intact worktree;
it is not a general-purpose Git branch rename. On a **fresh** ZIP, LOOSE also
allows `featureBranch=feature/other-name` at `APL` to select an effective
branch without rewriting the archived metadata:

```bash
apatch my-project-PATCH-new-feature featureBranch=feature/other-name \
  opSeq=APL,BRN,CHK,STS skipApproves=true
```

The CLI records this explicit effective branch and preserves the original ZIP
identity. It will not silently switch to an arbitrary branch. Branch creation
may stop if a local/remote feature branch or open PR cannot be reconciled.

## 4. Continue a feature with another ZIP

`LOOSE` (the default) supports iterative development: multiple patches on one
feature branch, manual edits and commits/pushes at separate times. For **each
new** ZIP, provide its name and opt into continuation:

```bash
apatch my-project-PATCH-followup opSeq=APL,CHK,STS \
  followup=true skipApproves=true
```

For a continuation, **omit `BRN`**. The CLI verifies that the selected current
feature branch, previous patch/session evidence, and history permit another
ZIP. It refuses unsafe duplication, conflicting branches, remote drift, and
unknown changes. Reapplying the *same* ZIP without inspection is not a normal
continuation strategy.

An explicitly chosen effective branch can be supplied when the new ZIP carries
a different proposed name:

```bash
apatch my-project-PATCH-followup featureBranch=feature/existing-work \
  followup=true opSeq=APL,CHK,STS skipApproves=true
```

If new ZIP paths overlap locally modified files, inspection and explicit
supervised approval can be necessary; unattended application may stop.
`apatch` preserves manual edits and can retain overlap backups, but a ZIP is
not an automatic three-way merge. Always inspect an overlap before accepting
an overwrite.

For advanced batch application, `handoffSeq` must explicitly identify **one
ZIP for each `APL`**; several ZIPs in one sequence are LOOSE-only. Example:

```bash
apatch opSeq=APL,BRN,APL,CHK,STS \
  handoffSeq=first.zip,second.zip skipApproves=true
```

Multiple `APL` entries require distinct ZIPs; the sequence must begin with
`APL,BRN`, may not perform a second `BRN`, and must apply all ZIPs before
commit/push/PR/merge/sync. This is an advanced alternative to separate
commands, **not** permission to ignore changed-path overlap or checked state.

## 5. Modes, actions and operation sequences

| Mode | When to use it |
| --- | --- |
| `LOOSE` (default) | Daily manual work, alternate/continued feature branches, multiple patches per commit, deferred push; all safety gates remain |
| `--strict` | Enforce strict phase, branch, and verification ordering; not a way to bypass source checks |
| `--force` | Recover supervised manual/interrupted workflows; **never** force-push or skip validation |

Choose an operation with `op=CODE` (or its stable number), or chain operations
with `opSeq=A,B,C`. The sequence stops at the first error, refused action or
unsafe no-op. It reports what ran and which steps remain; an included terminal
`STS` produces a read-only report. Reuse the cached handoff only after it has
been validated; do not assume a missing or corrupt cache represents the latest
ZIP.

| Number | Code | Meaning and important limit |
| ---: | --- | --- |
| 0 | `EXT` | Exit; not allowed inside `opSeq` |
| 1 | `BRN` | Create/prepare a feature branch; after ZIP-first APL, transfer pending work |
| 2 | `BAP` | Deprecated branch-and-apply for **legacy JSON** handoffs only |
| 3 | `APL` | Validate and apply an explicitly selected ZIP |
| 4 | `CHK` | Run the target project's canonical check list |
| 5 | `CMT` | Create a **local** commit; does not push |
| 6 | `PSH` | Non-force push with branch/remote checks |
| 7 | `PR` | Create or verify a single matching GitHub pull request |
| 8 | `MRG` | Guarded merge subject to GitHub review, CI, revision and gate checks |
| 9 | `SYN` | Synchronize the local base after a confirmed merge when still pending |
| 10 | `STS` | Inspect recorded local status; no live GitHub query |
| 11 | `AUD` | Audit repository patch history; optional explicit remote verification |
| 12 | `FMT` | Run configured **mutating** format commands; invalidates old checks |
| 13 | `REV` | Run configured independent script/LLM review after valid CHK |
| 14 | `BLD` | Run configured build commands only; **not** canonical verification |

Typical deliberately staged publication:

```bash
apatch opSeq=FMT,CHK,REV,STS skipApproves=true
apatch opSeq=CMT,PSH,PR,STS skipApproves=true
apatch opSeq=MRG,SYN,STS skipApproves=false
```

Use `FMT` only with `format_commands`, `REV` only when configured, and `BLD`
only with `build_commands`. A required independent review must be fresh before
`CMT`. Merge and sync may depend on current PR/CI state, so the last sequence
may need to be resumed separately after a verified external decision. Running
`skipApproves=false` allows normal confirmation prompts; it does not guarantee
that a guarded action will be allowed.

## 6. Checks, formatting, builds and review

**`FMT` is mutating.** It executes `format_commands`, so inspect the resulting
changes and run `CHK` again. Formatting and other preparation must never be
hidden inside a canonical check. `CHK` runs the `checks` list and confirms a
stable worktree/index; any changed check outputs, failed tests, changed HEAD,
or modified policy invalidate prior evidence. Source may be preserved for
inspection when a check stops, but an error is not a PASS.

**`BLD` is independent of `CHK`.** It runs `build_commands` and verifies that
building did not alter tracked worktree/index or branch/HEAD. It invalidates
previous `CHK`/`REV` evidence, even when it succeeds. `BLD` does not execute
the `checks` list, so a successful build must never be reported as verified
tests. In incremental LOOSE development, a deliberate build-only stage can
precede an unchecked commit only when configured gates permit it.

**`REV` requires checked input.** Optional review providers execute in
configured order, and a fresh successful review is required for commits when
`review_required: true`. A script review receives the diff on stdin and/or
a bounded file path; a model review must return a validated verdict:
`PASS`, `CHANGES_REQUIRED`, or `ESCALATE`. No result may be inferred from
missing output. Review is **not** a sandbox: configured processes run with the
invoking user's privileges and an external LLM command may disclose data.

Example optional review policy (only use providers you actually trust):

```yaml
review_required: true
review_timeout_seconds: 180
review_max_bytes: 131072
reviewers:
  - id: static
    kind: script
    command: ["./scripts/review.sh", "{diff_file}"]
```

For structured reports, raw stdout/stderr, normalized findings and bounded
LLM context, additional `review_*` settings enable private capture under
`.apatch/reviews/`. Capture and retention are opt-in. External disclosure
requires `review_context_external_consent: true` before including messages or
source diffs. Retention limits (`review_retention_max_runs`,
`review_retention_max_bytes`, `review_retention_max_age_days`) protect bounded
local storage when `review_retention_enabled: true`. Review evidence may
contain secrets; never commit it or equate it with GitHub approval. Selective
retrieval and metadata export are currently internal APIs, **not** general
public CLI actions.

### Deferred canonical checks in LOOSE

The project may choose the first action that must require checked evidence:

```yaml
disabled_without_chk: MRG
```

Supported values: `CMT` (default), `PSH`, `PR`, `MRG`. There is an equivalent
explicit LOOSE option, for example `disabledWithoutChk=MRG`. This permits
intentionally unchecked intermediate commits only within the applicable
LOOSE policy; it does **not** waive final verification, review/CI, remote
identity, or guarded-goal rules. `STRICT` and `FORCE` have different safety
contracts.

Example **incremental development**, with a real configured `build_commands`
list and an eligible existing feature session:

```bash
apatch incremental-patch opSeq=APL,BLD,CMT,PSH,STS \
  followup=true disabledWithoutChk=MRG skipApproves=true
```

Before the final merge, perform canonical checks on the **exact final commit
HEAD**, especially when previous commits were unchecked. A CHK before the
last commit is not sufficient to release the final unchecked history. Keep
`MRG` out of an unattended sequence until its fresh revision/CI/review gates
have been confirmed. A safe final-stage pattern can require two check passes:
one before committing the final patch, then one after committing/pushing the
final HEAD, before MRG. If the required final clean-HEAD check is missing,
`CHECK_GATE_MRG` blocks the merge.

## 7. Publication, PRs and synchronization

`CMT` stages/reconciles the intended changed files and makes a local Git
commit. In ordinary LOOSE workflows, extra manual edits can be included only
subject to the relevant scope/consent checks. In guarded goals, unknown manual
or already staged paths require explicit path-specific acceptance; unattended
`skipApproves=true` cannot classify them for you.

`PSH` uses a normal (non-force) push. It checks remote identity and ancestry;
it never force-pushes. `PR` confirms source branch, target base and pushed SHA
and can adopt a uniquely matching existing open PR rather than duplicating it.
An ambiguous or conflicting PR blocks publication. `MRG` checks actual GitHub
PR revision, required reviews, CI and mergeability. A CLI success message or
saved checkpoint does **not** substitute for live remote evidence. `SYN`
synchronizes local base after a confirmed merge when needed.

For a normal first patch, you can keep publication decisions separate:

```bash
apatch my-project-PATCH-feature opSeq=APL,BRN,CHK,STS skipApproves=true
apatch opSeq=CMT,PSH,PR,STS skipApproves=true
apatch op=STS
```

Then inspect the exact PR and CI results before explicitly requesting merge:

```bash
apatch opSeq=MRG,SYN,STS skipApproves=false
```

The merge step may itself confirm/synchronize the base; a subsequent `SYN` is
for an outstanding synchronization step, not permission to merge twice.
Neither local `CHK` nor a passing model `REV` overrides GitHub branch
protections. Unexpected remote outcomes must be reconciled before retry.

## 8. Guarded goals and named macros

**Direct `op`/`opSeq`** executes the requested operations in that order.
**Guarded `goal=`** first computes a plan from verified feature-session,
ZIP, Git and (when required) remote evidence. A plan is not a guarantee that
execution will succeed; safety checks run again at each step.

Supported goals are `CHECKED`, `COMMITTED`, `PUSHED`, `PR_CREATED`, `MERGED`.
`planOnly=true` displays a read-only plan. `intent=auto|new|continue` selects
the requested kind of feature session. Goals require LOOSE and a valid
self-contained ZIP, not a legacy JSON handoff.

```bash
apatch my-project-PATCH-feature goal=CHECKED planOnly=true
apatch my-project-PATCH-feature goal=COMMITTED skipApproves=true
apatch goal=MERGED planOnly=true
```

Named LOOSE macros provide commonly used guarded workflows:

| Macro (`op=...`) | Purpose |
| --- | --- |
| `APPLY_PATCH` | Apply and prepare feature branch, if not already safely satisfied |
| `APPLY_PATCH_CHECK` | Apply/prepare, then run canonical checks |
| `MERGE` | Resume an already applied, uniquely verified feature session and publish/merge as allowed |
| `RUN_ALL` | Full guarded lifecycle; may apply a new ZIP and reach merge/sync when all gates permit |

```bash
apatch my-project-PATCH-feature op=APPLY_PATCH_CHECK skipApproves=true
apatch op=MERGE skipApproves=false
```

Guarded macros can use `prepare_checks` and `check_worktree_policy` on
supported prepared-check paths; this is not the ordinary `FMT` operation.
They report executed, already satisfied, and not executed actions and attempt
a final `STS`. Remote macros **can push, create PRs, merge and sync**: inspect
the plan before invoking them. For unknown manual paths or an uncertain remote
result, they stop rather than silently continue.

## 9. Produce a ZIP from source (separate workflow)

The producer works in the **source repository**, and writes its output
**outside** that Git worktree. It is distinct from the consumer `APL` action.
First inspect what Git reports, including untracked files and deletions:

```bash
python3 /path/to/apatch/apatch_pack.py --project . --discover
python3 /path/to/apatch/apatch_preflight.py --project .
```

After reviewing the path set and secrets, produce an explicit overlay:

```bash
python3 /path/to/apatch/apatch_pack.py \
  --project . \
  --output /path/outside/project-PATCH-example.zip \
  --branch feature/example \
  --message "feat: deliver example" \
  --include src/example.py \
  --include tests/test_example.py \
  --delete src/old_example.py
```

Use repeated `--include` for new/modified files, and `--delete` **only** for
files tracked in the destination baseline that are actually being removed.
`--prepare` opts into mutating formatting before checks; without it, the
producer's preflight runs read-only checks. The producer verifies the exact
source bytes and modes; it will not silently overwrite an existing output.
Optional `--base-commit` must be a verified **destination** Git commit, not a
guess from the source checkout. Run `apatch_pack.py --help` for all producer
options and provenance requirements. A successfully packaged ZIP is **not**
evidence that it was applied, tested, committed or merged in the destination.

## 10. Diagnose, recover and resume safely

Start with **read-only evidence** whenever an operation stops:

```bash
apatch op=STS
apatch op=AUD
apatch op=AUD verifyRemote=true
apatch info=PROGRESS
```

`STS` is a local patch status and may use a verified cache; `AUD` reconciles
local created/applied histories, journals and checkpoint evidence. The remote
option makes bounded explicit GitHub reads; offline `STS` and `AUD` cannot
prove PR/merge outcomes. `info=PROGRESS` reads tool-wide recorded events and
does not need a handoff or repository selection.

| Symptom | Likely cause | Safe next action |
| --- | --- | --- |
| `git ls-files --error-unmatch ...` during APL | ZIP `delete_paths` names a path not tracked by this target revision | Stop; compare current Git manifest with ZIP metadata, regenerate ZIP against the correct base |
| ZIP base/branch/HEAD mismatch | The target moved since the patch was prepared, or a branch is still in use | Verify `git status`, base HEAD, remote and ZIP origin; rebase the **producer overlay**, not the working tree blindly |
| `APL` interrupted after some files were written | Multi-file extraction was interrupted; checkpoint may say `applying` | Preserve worktree; inspect status, recorded paths, runtime backups and operation journal before recovery |
| `APL` finished but `BRN` stopped | Pending ZIP bytes must remain on the original base HEAD | Inspect `STS` and Git; resume BRN or use permitted `featureBranch` reassignment, without another APL |
| Patch was already applied | Cached/history evidence says the selected ZIP is not new | Resume pending steps on verified bytes, not duplicate extraction |
| `CHK` changed files or timed out | A configured check mutated output or failed/ran too long | Preserve edits, inspect console, move formatting to FMT, then rerun CHK on the corrected snapshot |
| `BLD` passed, `CMT` blocked | Build is not canonical verification, or the chosen check gate is earlier | Run CHK or correct the explicitly configured LOOSE gate; do not claim the build satisfied CHK |
| `CHECK_GATE_MRG` | Final clean committed HEAD has not been canonically checked | Run CHK on the exact final HEAD and revalidate the PR/CI state before retrying MRG |
| `PR`/`MRG` returned an uncertain result | The remote may have succeeded despite lost confirmation | Inspect exact PR number, head SHA, GitHub state and history; do not blindly retry a remote mutation |
| `SYN` stopped after a merge | Local base may not yet match confirmed merged remote state | Verify the remote merge and local branch, then resume only the remaining synchronization step |

When a ZIP application overlaps manual work, inspect the specific changed
paths and any `.apatch/backups/` created by recovery; never delete or reset
files just to make a check pass. Runtime state and patch registries are
important recovery evidence, not permission to infer a successful remote
operation. Locks, atomic journal writes and digest checks reduce risk but
cannot make external GitHub actions crash-atomic. A verified full finished
sequence may report `ALREADY_COMPLETED` without replaying its actions.

**Avoid:** `git reset --hard`, manual history edits, `git push --force`,
`FORCE` as a substitute for a corrected ZIP, rerunning APL after confirmed
success, and treating `skipApproves=true` as unattended authorization for
unknown file paths or remote mutations.

## 11. Security, privacy and compatibility

ZIP content and configured scripts are untrusted until reviewed. Even a
structurally safe ZIP may add malicious Python or shell code; configured
checks/reviewers execute with your user permissions. Keep secrets outside
patches, configs, check output, review artifacts and Git commits. `apatch`
prints canonical check output in the console but does not maintain a full
persistent transcript of successful checks; review and failure diagnostics
are separately bounded. Sensitive review files remain private to the target.

The installed runtime may lag behind the repository snapshot. If your `apatch
--help` lacks `BLD`, `disabledWithoutChk`, `featureBranch`, multi-ZIP
`handoffSeq`, or another example in this guide, upgrade/verify the **installed**
CLI before using it; do not assume editing the source checkout upgrades the
running deployment. Native Windows behavior is not verified; supported
POSIX-target behavior must be tested in its actual environment.

For architecture and security guarantees, see [Architecture](ARCHITECTURE.md).
For independent project verification, see its
[development and verification section](ARCHITECTURE.md#development-and-verification).
