---
type: Module Contract
title: Feature Sessions Contract
description: Session identity, continuation admission and guarded commit scope boundaries.
---
# Feature Sessions Contract

`apatch_lib.mo_feature_sessions.api` exposes additive feature-session identities,
read-only context and continuation evidence, and guarded commit-scope inspection.
The module never publishes, merges, changes Git refs or independently authorizes
new ZIP application. Coordinators decide when to act on its evidence.

- `session.py` owns the existing persisted `feature_sessions` schema, strict
  validation, identity fingerprints and explicit session lifecycle. Its
  validation operates on supplied state dictionaries without opening storage.
- `session_continuation.py` verifies current repository, history, branch, remote
  and checkpoint evidence for an explicit continuation request. Unknown or
  contradictory evidence must stop the operation before source changes.
- `commit_scope.py` fingerprints the approved path set and rejects intervening
  worktree/index/policy changes; a valid scope is not permission to skip CHK.
- `context.py` classifies read-only evidence and describes blockers for guarded
  goals. It does not convert unknown remote outcomes into success.

Existing `apatch_lib.session`, `session_continuation`, `commit_scope` and
`context` imports remain identity-preserving compatibility aliases, including
historical `unittest.mock.patch` targets. State I/O remains in `mo_storage`;
continuation/context readers depend on that storage boundary, while storage
uses only the pure session validator. The two packages are not independently
initializing coordinators. Existing callers retain their signatures and errors.
