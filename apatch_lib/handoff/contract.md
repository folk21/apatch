# Handoff module contract (R2.2 metadata boundary)

## Ownership

`handoff` owns the immutable `Handoff` value object, schema-v1 metadata keys,
validation expressions, JSON decoding, and repository-relative path checks.
Archive inspection, extraction, packaging, history, and resume are **not**
relocated by R2.2; they remain in their existing modules until R3.

## Public API

`handoff.api` exports `Handoff`, `load_handoff(path: Path) -> Handoff`,
`parse_handoff_payload(payload, *, embedded=False) -> Handoff`,
`safe_relative(path: str) -> str`, and the four historical regex constants.
`model` temporarily re-exports these exact objects for existing consumers.

## Invariants and error semantics

- Embedded metadata rejects `patch_sha256`; legacy JSON may contain it.
- Reject unsupported schema versions and unrecognized fields, unsafe names,
  incorrect hash lengths, invalid feature branches, and unsafe deletion paths.
- Preserve the normalized commit message, existing error texts, constructor
  arguments, and `Handoff.subject` behavior.
- JSON loading reads the supplied path only; no repository, ZIP, history, or
  Git/GitHub operation is performed. Invalid JSON and unsafe values raise
  `core.api.Abort` with the existing error contract.
- No filesystem or subprocess operations occur in `handoff.models` or
  `handoff.constants`; all I/O for legacy JSON stays in `handoff.parsing`.

## Dependencies and tests

Only Python standard libraries and `core.api` are dependencies for this slice.
The remaining handoff domain must not acquire workflow or publication imports.
Test with `tests.test_domain_model_boundaries`, `tests.test_validation`,
`tests.test_handoffs`, and the opt-in characterization suite.
