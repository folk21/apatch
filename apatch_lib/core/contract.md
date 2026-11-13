# Core contract

## Ownership

The core package owns cross-domain, side-effect-free fundamentals only.
`core.api.Abort` (implemented in `core.errors`) is the stable base for fail-closed precondition failures.

## Public contract

- `core.api.Abort` (implemented in `core.errors`) inherits `RuntimeError`. Historical `model.Abort` is an identity alias.
- Raising a domain-specific subtype must remain catchable as `Abort`.
- No configuration, filesystem, Git, GitHub, workflow or handoff imports may enter `core.errors`.

## Migration status

`core.actions`, `core.enums` and `core.contracts` remain compatibility owners
until later migration slices. This contract applies to `core.errors` now; it
does not imply the other modules have already moved.
