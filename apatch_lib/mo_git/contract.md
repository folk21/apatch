---
type: Module Contract
title: Git module contract — R3.1 inspection / R3.2 command execution
description: Git adapter responsibilities, command execution, and safe repository operations.
---
# Git module contract — R3.1 inspection / R3.2 command execution

**Status:** read-only inspection and command execution ownership implemented; guarded mutation policy is deferred.

## Responsibility and API

`apatch_lib.mo_git.api` publishes `RepositorySnapshot`, `WorktreeEntry`,
`WorktreeSnapshot`, `inspect_repository(root)`, `inspect_worktree(root)`,
`worktree_inventory(root)`, `worktree_change_details(before, after)`,
`current_branch(root)`, `head(root)`, `repository_root(cwd, expected_name)`,
`status_paths(root)` and `worktree_fingerprint(root)`.

- `inspect_repository` requires the exact repository root and a named branch.
  It reports branch, HEAD, and the observed dirty flag; it does not fetch refs.
- `inspect_worktree` captures sorted paths, index entries, file SHA-256,
  executable bits, and symlink targets. It fails closed on observed fingerprint,
  changed-path, branch, or HEAD drift during capture. An external writer could
  still race after the return; callers MUST revalidate before mutation.
- Both snapshot DTOs and `WorktreeEntry` are frozen. `models.py` has no
  filesystem, subprocess, network, or config-loading logic.
- `worktree_change_details` is pure and does not expose file contents.

## Dependencies and side effects

`mo_git.commands` owns the argv-only subprocess transport, command deadlines,
streamed check output, bounded failure summaries and redacted logging.
`mo_git.repository` owns branch, HEAD and worktree queries, dispatching calls
through its patchable `commands.run` dependency. `mo_git.inspection` captures
worktree snapshots using `repository` and `commands` APIs. There is no root
`gitutil.py` facade. Command execution is an internal transport, not a new
mutation authorization; `mo_git.api` exposes read-only operations only.

The read-only inspection APIs perform no Git writes, external network,
confirmation prompts, or lifecycle checkpoint updates.
The Git domain may depend on the neutral `core` exception and standard
library, never on `handoff`, `publication`, `review`, or `workflows`.

Approval context and prompts belong to `mo_presentation.confirmation`.
Removing the Git compatibility facade changes no command admission, consent,
retry or workflow safety policy. The transport remains separate from authorization.

## Compatibility and tests

Consumers import `WorktreeEntry`, `worktree_inventory` and
`worktree_change_details` from `mo_git.api` or their owning modules.
The removed root `gitutil.py` import is intentionally unsupported; no stored
state or ZIP metadata changed.

Contract tests: `tests/test_git_domain_boundaries.py`,
`tests/test_artifact_preflight.py`, `tests/test_artifact_packaging.py`,
`tests/test_safety.py`, and opt-in characterization tests.

R3.2 focused tests: `tests/test_git_command_boundaries.py`, plus
`tests/test_safety.py`, `tests/test_timeout_reporting.py`, and
`tests/test_git_domain_boundaries.py`. Run regular and characterization gates.
