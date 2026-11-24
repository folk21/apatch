---
type: Architecture
title: Architecture
description: Architecture boundaries, Git/ZIP safety, evidence pipeline, recovery, and verification ownership.
---
# Architecture

`apatch` is a Python CLI for verified ZIP patch handoffs and guarded Git/GitHub workflows. This document describes ownership, data flow, safety and development checks; [Usage](USAGE.md) documents commands and configuration, while module-level `contract.md` files define their public APIs. It is not an SDD normative specification.

## Component flow

1. `apatch.py` parses `mo_cli.api.CliRequest` and calls `apatch_lib/application.py`. Read-only status, audit and progress do not initialize writable workflow state.
2. `handoff_selection.py` and `mo_handoff/api.py` select a ZIP, explicit legacy JSON or verified cache. Archive metadata and extraction are validated by the handoff domain before source files change.
3. `workflow.py`, `sequence.py` and `action_executor.py` coordinate operations. `branch_patch.py` prepares branches and extracts patches; LOOSE, STRICT and FORCE have separate, explicit gates.
4. `mo_git/api.py`, `gitutil.py` and `github.py` own Git/GitHub effects. Review and publication check current branch, HEAD, remote and exact PR revision before acting.
5. `state.py`, `mo_handoff_history/` and `operation_events.py` record workflow state, applied ZIPs and attempts. `progress.py` maintains separate bounded installed-tool-wide summaries. Local recorded history cannot replace live GitHub evidence.

## Ownership map

| Concern | Owner / boundary |
| --- | --- |
| CLI grammar, navigation | `apatch.py`, `mo_cli/`, `application.py` |
| ZIP schema, safe archive extraction, cache | `mo_handoff/` (internal `cache/` and `resume/`), `handoff_selection.py`, compatibility `patch.py` / `params_cache.py` |
| Archive generation | `mo_handoff_producer/`, compatibility `artifact_packaging.py` and `artifact_preflight.py` |
| Workflow phases, actions, modes, goals | `workflow.py`, `mo_workflows/`, `loose.py`, `force.py`, `planner.py`, `macros.py` |
| Feature sessions, scope verification | `session.py`, `session_continuation.py`, `commit_scope.py`, `context.py` |
| Configuration and validation | `mo_configuration/api.py`, `mo_configuration/loaders.py`, `mo_configuration/validators.py` |
| Git and GitHub publication | `mo_git/`, `gitutil.py`, `mo_publication/github.py`, `mo_publication/branch_guard.py` |
| Review and evidence | `mo_review/` (execution, normalization, capture, context, retrieval, retention) |
| Audit, checkpoint, logs, progress | `mo_audit/`, `state.py`, `operation_events.py`, `logging_setup.py`, `progress.py` |

Canonical module owners live directly under `apatch_lib/` and use the `mo_` prefix. The `cache/` and `resume/` subpackages are internal implementation details of `mo_handoff`, with their public protocols defined in `mo_handoff/api.py`. Only `mo_handoff_history` and `mo_handoff_producer` remain separate handoff-related module owners. Deprecated import paths remain compatibility aliases, not additional owners. `mo_cli` owns CLI syntax/help/inspection dispatch; `mo_presentation` owns terminal rendering, while root `status.py` retains read-only workflow evidence and identity. `mo_audit` owns read-only audit collection/rules/reconciliation; `mo_publication` owns GitHub mutation guards; and `mo_review` owns the review evidence pipeline.

Use stable `api.py` and `contract.md` boundaries for cross-domain calls; compatibility adapters preserve old imports. Avoid deep peer-to-peer imports, hidden mutable global state, duplicate validation and dependency cycles. Keep module contracts next to code, not in general documentation.

## Architectural dependency rules

The historical modular redesign is superseded by implemented module APIs and
colocated `contract.md` files. The CLI/application layer composes domain owners;
Git, handoff, publication and review remain independent effect/validation
boundaries. Favor one-way dependencies and exact source-tested behavior over
proposed package names. Contract ownership, action compatibility and recovery
guarantees must be validated against the current source, never a redesign diary.

## Configuration and persistence

`apatch.conf` lives in the installation and defines global paths, limits, remote/base defaults and approval policy. The **target** repository's tracked `.apatch/config.yaml` owns its canonical `checks`, optional `build_commands`/`format_commands`, reviewers and bounded settings. Project overrides have defined precedence and schema-v1 validation. Configured commands execute as argv, without implicit shell interpolation; running a shell script explicitly can still execute arbitrary code.

Each target keeps its own ignored `.apatch/` runtime state: cached handoff parameters, workflow checkpoint, applied-patch history, optional created-patch registry, operation journal, private logs/backups/reviews. Files are validated for regular type and safe location; sensitive or mutable records use dedicated locks, restricted modes and atomic replacement as appropriate. A lock protects serialization, not remote transaction atomicity. Existing state and legacy JSON/ZIP protocols remain readable through explicit compatibility paths.

The selected ZIP digest and handoff signature bind an application attempt to its checkpoint, applied-history entry and successful `APL` journal run. The verifier rechecks live Git state for replay-free resume. A verified repeated `APL`/`BRN` prefix is reported as already satisfied; an unresolved or mismatched archive is not replayed merely because it was named again.

## Mode, checks and publication boundaries

**LOOSE** allows manual development, multiple patches per commit and deferred publication. **STRICT** guards phase and branch transitions. **FORCE** is recovery only, not force push. `skipApproves=true` removes questions but never disables safety gates. New feature branches must pass unfinished-branch inspection; an inability to prove remote/PR completion fails closed. Direct actions are explicit; guarded goals and macros derive steps from session evidence and revalidate at each transition.

`CHK` invokes the target's canonical checks on an observed revision; `FMT` and optional `BLD` use separate project commands. Builds do not prove tests. Review (`REV`) is opt-in, performed after appropriate CHK evidence and invalidated by drift. `review_required: true` makes its passing evidence a separate local commit gate where applicable. Where installed, `disabled_without_chk` may defer the compulsory CHK boundary to `CMT`, `PSH`, `PR` or `MRG`; the final verification must bind to the exact commit tree. It does not permit bypassing stricter guarded-goal, review, GitHub CI or merge requirements.

Guarded commits authorize only session-owned ZIP footprints or specifically approved manual paths. Unknown pre-staged files, rename/copy ambiguity and stale evidence block unattended execution. Git stage/index, worktree, policy and HEAD are fingerprinted; the resulting commit tree must match the verified staged tree. A failed stage or Git hook does not trigger an automatic reset. Direct LOOSE commits retain their separately guarded interactive path.

Push is non-forced and requires compatible local/remote ancestry. PR creation checks for one matching open PR with the intended branch, base and exact pushed SHA; an existing matching PR is reused, not duplicated. A changed or ambiguous PR causes a stop. Merge requires fresh live PR source SHA, review, CI and mergeability evidence. `MRG` and local base `SYN` are distinct effects; an uncertain merge response must be reconciled before any mutation retry.

## Review evidence boundary

`13 [REV]` runs explicitly configured script and LLM executables only after
fresh `CHK` evidence. Executables use the invoking user's OS permissions;
scanner output, LLM responses, paths and finding text are **untrusted data**,
not executable instructions. A failed command, invalid verdict or changed
source/index/branch/policy snapshot cannot be recorded as a passing review.
The complete review verdict remains independent of GitHub approval and CI.

### Local evidence lifecycle

The review pipeline has separate, opt-in boundaries:

| Boundary | Owner | Data and safety guarantee |
| --- | --- | --- |
| Capture | `review_artifacts.py`, `code_review.py` | `review_artifacts_enabled` defaults to false. When enabled, `REV` writes separate bounded stdout/stderr streams, SHA-256 metadata and an atomic `manifest.json` under ignored `.apatch/reviews/review-<24-hex>/`. Review directories are private (`0700`), files are private (`0600`). |
| Normalization | `review_normalizer.py` | Structured scanner reports keep tool status, finding identity and provenance. Wrapper exit code zero does not establish that all required scanners succeeded or that there are no findings. |
| LLM context | `review_context.py` | The compact context has a byte budget and defaults to metadata only. Finding messages and source diff require explicit `review_context_external_consent` plus their individual inclusion settings. |
| Retrieval | `review_evidence_api.py` | `ReviewEvidenceSession` is an internal, snapshot-scoped and quota-limited local reader. It verifies finding IDs, saved digests and current source bytes using no-follow file access; it cannot call reviewers or external models. |
| Retention and export | `review_retention.py` | Private storage locks and verified member inventories constrain cleanup. `prune_review_artifacts()` previews by default; `export_review_summary()` requires explicit `consent=True` and returns bounded, metadata-only JSON. Neither is a public CLI action or a network transport. |

A manifest records `STARTED`, `FAILED` or `COMPLETED`; a terminal status
alone is not a trusted result. Review replays and lookups must verify the
stored inventory and its hashes before using evidence. Retained output can
contain credentials or private source text: it is not included in handoff ZIPs,
commits or ordinary operation logs.

### Retention and interruption recovery

Automatic pruning is **disabled** until `review_retention_enabled: true` is
configured. When enabled, `REV` acquires the project-local review-storage lock
and evaluates configured count, age and byte limits **before** allocating the
next run. This is an allocation guard, not a background service or filesystem
quota. Unknown names, symlinks, hardlinks, partial manifests, `STARTED` runs,
modified bytes and other unverified evidence remain protected. If that
protected evidence makes capacity uncertain, the reviewer does not start.

Explicit `prune_review_artifacts(root)` is a dry-run preview; deletion needs
an explicit non-preview call or the retention opt-in. Eligible verified
terminal runs are pruned oldest first and journal their exact remaining
members before deletion. After an interruption, a subsequent maintenance
attempt revalidates that journal and any remaining files, including a
previously interrupted final directory removal; unexpected members stop
cleanup instead of being erased. Storage lookup errors, unknown paths and
changed manifests are safety failures, not permission for a best-effort
recursive deletion. Pruning never deletes Git state or pretends that a removed
review was accepted. Missing/pruned/corrupt evidence fails closed on future
retrieval/export rather than being silently recreated.

The internal `export_review_summary(root, review_id, consent=True)` validates
terminal evidence and returns at most 8,192 bytes of provider/run references,
statuses and a manifest hash, without prompts, source excerpts, finding
messages or raw logs. Export consent does not trigger a transfer; callers own
any subsequent disclosure. User-facing configuration and commands are
specified in [Usage](USAGE.md#6-checks-formatting-builds-and-review), while
module-level interfaces remain owned by source and `contract.md` files.

## Security and recovery

`apatch` **is not a sandbox**. A ZIP is untrusted source; even a structurally valid archive may contain malicious code. Canonical checks and reviewers run with the invoking user's OS privileges. Review archives and executable commands before unattended operations or publication.

| Boundary | Enforced condition | Failure or residual risk |
| --- | --- | --- |
| ZIP files | Root confinement, safe member types/paths/deletions, size limits, digest and collision checks | Content may still be unsafe; multi-file extraction is not crash-atomic |
| Runtime and Git | No-follow/regular file validation, locks, history integrity, worktree preservation, branch and HEAD rechecks | Crash or external edits may leave a partial state requiring inspection |
| Checks and review | Explicit configured argv, total/idle timeouts, bounded output and consent gates | Executed scripts have full user permissions; stored artifacts may contain secrets |
| GitHub operations | Non-force push, unique exact PR identity, review/CI/mergeability checks and read-only reconciliation | Remote mutation can succeed with a lost response; never blindly retry |

If an `APL`/`BRN` operation stops, inspect `git status`, `apatch op=STS`, the project checkpoint, applied-patch journal and any `.apatch/backups/`; do not discard uncommitted work, delete unknown runtime files or replay extraction without proof. `STS`/`AUD` distinguish recorded, verified, unknown and conflict evidence; offline status is not a live GitHub fact. On failed `SYN`, confirm the merge before retrying synchronization. For checked reviews, missing/pruned evidence is not recreated automatically. Runtime locks use POSIX `fcntl`; Linux and macOS are supported targets, while native Windows is not verified. Automated GitHub behavior is tested with mocks, not live publication.

## Development and verification

Use Python 3.10+, Git and the dependencies from `requirements.txt`. The standalone installer and alternate source-checkout setup are described in [Installation](INSTALLATION.md). Run tests and SDD validation from the project checkout:

```bash
sh ./run_tests.sh
sh ./run_rare_checks.sh
python3 tools/specs/validate_state.py
python3 tools/specs/validate_features.py
sh -n apatch.sh
sh -n run_tests.sh
sh -n run_rare_checks.sh
```

`run_tests.sh` is the regular bounded suite; `run_rare_checks.sh` is the extended regression suite. They use isolated temporary Git repositories, mocked GitHub interactions and bounded subprocess workers/timeouts with limited retries. Optional non-mutating quality checks are `sh ./run_quality.sh lint|types|all` after installing `requirements-quality.txt`; missing tools report `NOT_RUN`, not PASS. Use focused `python3 -B -m unittest` invocations before full suites. `tools/specs/validate_state.py` verifies the tracked SDD processing checkpoint, not runtime state. Tests on Linux do not establish macOS behavior. Report exact checks, failures, timeouts and untested environments; do not weaken assertions or safety gates to make a run green.

Specifications are indexed in [docs/specs/README.md](specs/README.md); agent-facing SDD lifecycle rules live in [docs/specs/AGENTS.md](specs/AGENTS.md). The newest verified source and actual tests outrank historical stage prose. Do not present an unaccepted draft or a generated ZIP as proof of merge or product deployment.