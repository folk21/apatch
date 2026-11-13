# Configuration module contract

## Purpose

Configuration owns global INI and project YAML loading, all validation and
precedence decisions, and the immutable effective `Config` value. It never
executes configured commands or mutates the repository.

## Public API

`configuration.api` exports `Config`, `load_config(installation)`,
`load_project_config(root, global_config)`, `validate_base_branch(value,
source=...)`, `validate_log_subdirectory(value)`, and
`validate_runtime_filename(value)`. The legacy equivalents in `model` are
identity aliases. All errors remain `Abort` or its existing subtypes.

## Models and dependencies

`configuration.models` defines only the frozen `Config` DTO; loaders and
validators are separate effect and pure-policy files. Review-provider model
values are owned by `review.models`. The configuration loader temporarily
depends on those types to preserve the existing `Config.reviewers` data
contract; this dependency must be replaced with an explicit validated
configuration/review boundary before R2 is considered complete.

## Invariants

- Global INI and project YAML precedence, exact defaults, provenance fields
  and error categories are unchanged.
- Project settings reject unsafe symlinks, invalid schema, malformed commands,
  invalid booleans, out-of-range numeric policy, and conflicting filenames.
- Loading does not stage, commit, apply, publish, or change runtime state.
- All configuration reads are bounded by the existing source contract.
