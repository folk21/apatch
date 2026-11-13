# Workflows module contract (R2.3 value boundaries)

## Ownership and public API

`apatch_lib.workflows.api` is the stable public import surface for workflow
state shapes, phase/action identifiers, action-result outcomes and workflow
verification errors. The plural `workflows` package is intentional:
`apatch_lib/workflow.py` is the existing engine module and must not be shadowed
by a same-named package before the separately tested engine migration.

- `WorkflowRecord` and `StateDocument` are persisted-state `TypedDict` views
  declared in `models.py`. They do **not** validate or write stored JSON.
- `WorkflowPhase`, `OperationOutcome`, `PHASE_VALUES` are declared in `enums.py`.
- `ACTION_CODES`, `action_number` are declared in `actions.py`; existing numeric
  positions and mnemonics stay unchanged.
- `ActionResult` lives in `results.py` because its completion factories and
  outcome mapping are workflow behavior, not passive model declarations.
- `CheckWorktreeChanged` lives in `errors.py` and inherits `core.api.Abort`.

## Dependencies, effects and errors

The public value contract imports only its owning pure modules,
`core.api.Abort`, and `publication.api.RemoteOutcomeUnknown`. The result
classifier treats unknown remote effects as indeterminate even when an earlier
prompt was declined. An unsupported action return raises `TypeError`.

Importing `workflows.api` has no Git, filesystem, network, configuration-load,
workflow-engine initialization, lock, or checkpoint side effects. All state
writes, optimistic guards, phases, branch checks and publication remain in the
existing engine/adapters until R5. No new persisted schema or CLI operation
is introduced by this extraction.

## Transitional compatibility and recovery

Historical imports from `core.actions`, `core.enums`, `core.contracts` and
`model.CheckWorktreeChanged` are identity-preserving aliases. The `core`
facades are a *documented temporary exception* to the intended no-domain-
dependency rule; retire them only after consumer migration and reviewed public
compatibility policy. They do not contain duplicate policy.

Preserve unknown state extensions during storage validation and retain existing
migration, locking, failure, no-op and recovery semantics. `skipApproves=true`
removes prompts but never changes action eligibility.

## Verification

`tests/test_workflow_domain_boundaries.py`,
`tests/test_explicit_action_results.py`, `tests/test_operation_journal.py`,
`tests/test_modes.py`, `tests/test_sequences.py`, and opt-in characterization
workflow/recovery tests. Full engine relocation is deferred to R5.
