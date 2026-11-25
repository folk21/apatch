---
type: Module Contract
title: Publication module contract
description: GitHub PR identity, guarded remote publication, and uncertain-effect recovery boundaries.
---
# Publication module contract

## Ownership

`mo_publication` owns the `RemoteOutcomeUnknown` safety exception, typed
GitHub PR response representations, guarded GitHub CLI/PR/merge operations,
remote branch checks, and local base synchronization after verified merge.

`mo_publication.api` is the effect-free value/error interface. The explicit
`mo_publication.github` and `mo_publication.branch_guard` implementation
modules own executable publication boundaries. Their invocation remains
under the existing workflow's approval, revision, CI/review, and Git gates.

## Invariants and failure semantics

- `RemoteOutcomeUnknown` inherits the common `Abort` contract; unknown remote
  effects must not be replayed as if a local action definitely failed.
- Pushes remain non-forced; PR operations require matching branch/base/source
  SHA and fresh live evidence before a merge or local sync.
- `GitHubPr` and `GitHubPrIdentity` preserve their wire-field structure.
- Legacy `apatch_lib.github` and `apatch_lib.branch_guard` imports resolve to
  the same modules as their canonical implementation paths, including mocks.
- No independent remote action is authorized by importing this module.

## Dependencies and verification

`publication.models` uses only `typing`, and `publication.errors` uses the
common exception. Publication operations use the existing Git adapter and
configuration contracts. Test with `tests.test_github`, `tests.test_branches`,
`tests.test_publication_goals`, the module ownership tests and the canonical
`run_tests.sh` gate. Real GitHub execution is not tested by local fixtures.
