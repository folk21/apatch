# Core contract

## Ownership

`core.api.Abort` (from `core.errors`) is the domain-neutral base for
fail-closed precondition failures. No Git, ZIP, GitHub, workflow state,
configuration loading, or filesystem I/O belongs in the implemented core.

## Public contract

- `core.api.Abort` inherits `RuntimeError`; `model.Abort` is an identity alias.
- Domain-specific errors remain catchable as `Abort`.
- `core.errors` has no higher-level domain dependencies or side effects.

## Transitional compatibility

`core.actions`, `core.enums`, and `core.contracts` are **legacy import
facades** into `workflows.api` and `publication.api`. They are not core-owned
implementations, have no independent policy or persistence, and are explicit
migration exceptions to the final dependency graph until R5 and compatibility
review. New consumers must use the owning domain API.
