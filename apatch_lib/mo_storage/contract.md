---
type: Module Contract
title: Storage Contract
description: Atomic project state, operation evidence and installed-tool progress persistence.
---
# Storage Contract

`apatch_lib.mo_storage.api` exposes checkpoint, append-only operation-attempt
and bounded progress interfaces. The module records facts, not authority for
Git/GitHub lifecycle transitions.

- `state.py` retains schema-v1 reading/upgrade, schema-v2 validation, bounded
  reads, locked writes and atomic replacement; failed writes preserve prior
  state or report an error. It invokes the pure feature-session validator.
- `operation_events.py` retains bounded STARTED/terminal run validation and
  outcome mapping. An unconfirmed remote result remains indeterminate.
- `progress.py` persists installation-wide activity separately from target
  Git repositories; rendered summaries represent recorded facts only.
- `migration.py`, `local_ignore.py` and `logging_setup.py` retain their existing
  responsibilities for legacy local state, runtime Git exclusions and bounded
  diagnostic logging. `locking.py` provides the shared no-follow POSIX lock.

Existing `apatch_lib.state`, `operation_events`, `progress`, `migration`,
`local_ignore` and `logging_setup` imports retain exact module identity,
including patchable attributes. No schema, directory layout, lock names,
commit authorization or remote side effects change in this migration.
