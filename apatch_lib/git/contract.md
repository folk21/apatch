# Git module contract — R3.1 inspection / R3.2 command execution

**Status:** read-only inspection and command execution ownership implemented; guarded mutation policy is deferred.

## Responsibility and API

`apatch_lib.git.api` publishes `RepositorySnapshot`, `WorktreeEntry`,
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

The R3.1 snapshot functions still use the historical `gitutil` call-time seams
for `status_paths` and Git commands. In R3.2, `git.commands` owns the existing
argv-only process transport, with captured-command deadlines, streamed checks,
bounded failure summaries, and redacted logging. `gitutil.run`,
`display_command`, and the legacy helper symbols are identity-preserving
imports of this implementation; `gitutil.output` continues to dispatch
through its patchable `gitutil.run` global. Existing Git/CLI operations
remain the only mutation authorities: `git.commands.run` is an internal
transport, NOT a newly authorized mutation entry point. The public
`git.api` adds no command execution or mutation endpoint in R3.2.

The read-only inspection APIs perform no Git writes, external network,
confirmation prompts, or lifecycle checkpoint updates.
The Git domain may depend on the neutral `core` exception and standard
library, never on `handoff`, `publication`, `review`, or `workflows`.

The approval context and user prompts remain in `gitutil` until the runtime
confirmation boundary is designed. Moving the subprocess transport does not
change command admission, user consent, retry decisions, or workflow safety.
The transport cannot be treated as an authorization or policy interface.

## Compatibility and tests

Historical imports `gitutil.WorktreeEntry`, `gitutil.worktree_inventory`,
and `gitutil.worktree_change_details` remain the identical objects from this
package. Existing producer consumers are moved to `git.api` in R3.1; other
consumers migrate gradually. No stored state or ZIP member changes.

Contract tests: `tests/test_git_domain_boundaries.py`,
`tests/test_artifact_preflight.py`, `tests/test_artifact_packaging.py`,
`tests/test_safety.py`, and opt-in characterization tests.

R3.2 focused tests: `tests/test_git_command_boundaries.py`, plus
`tests/test_safety.py`, `tests/test_timeout_reporting.py`, and
`tests/test_git_domain_boundaries.py`. Run regular and characterization gates.
