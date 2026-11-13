# Publication module contract (R2.2 value and error boundary)

## Ownership

`publication` owns the `RemoteOutcomeUnknown` safety exception and typed
GitHub PR wire-response representations. GitHub CLI calls and the PR lifecycle
remain in the legacy `github.py` adapter until R4.

## Public API

`publication.api` exports `RemoteOutcomeUnknown`, `GitHubPrIdentity`, and
`GitHubPr`. `model.RemoteOutcomeUnknown` and `core.contracts.GitHubPr`/
`GitHubPrIdentity` remain exact identity aliases until their old consumers
migrate. The wire-field spelling is intentionally unchanged.

## Invariants and failure semantics

- `RemoteOutcomeUnknown` is still a subclass of `core.api.Abort`.
- A publication command with an uncertain result must remain `UNKNOWN_REMOTE_RESULT`
  rather than being treated as a generic failed local action or automatically retried.
- The owner models are typed structural views, not executable PR adapters;
  no network, file, or Git operations occur when they are imported.
- GitHub repository identity, SHA, state and CI/review requirements remain
  enforced by the existing GitHub adapter, not by these DTO definitions.

## Dependencies and tests

`publication.models` depends only on `typing`; `publication.errors` depends
only on `core.api`. The transitional `core.contracts` import alias is an
explicit R2 compatibility exception and is removed in the workflow-model
migration. Tests: `tests.test_domain_model_boundaries`,
`tests.test_explicit_action_results`, `tests.test_github`, and
`tests.test_operation_journal`.
