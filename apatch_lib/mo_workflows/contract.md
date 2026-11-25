---
type: Module Contract
title: Workflows module contract
description: Workflow orchestration, phase/value APIs, action execution, and mode-specific safety boundaries.
---
# Workflows module contract

## Ownership and public interfaces

`apatch_lib.mo_workflows.api` remains the import-safe public **value** API: action
identifiers, persisted-state type views, result classification, phase values and
workflow-specific exceptions. Importing that API does not initialize the engine,
filesystem, Git, or checkpoint storage.

`apatch_lib.mo_workflows.workflow.Workflow` owns the runtime engine and explicit
phase transitions. `loose.py`, `force.py`, `branch_patch.py`, and
`branch_reassignment.py` implement mode-specific and branch lifecycle rules;
`action_executor.py` and `action_applicability.py` implement step dispatch and
availability; `sequence.py`, `planner.py` and `macros.py` coordinate explicit
sequences and guarded higher-level goals. `status.py` owns read-only workflow
evidence, patch identity and next-action guidance; presentation renders those values. The application layer composes the
engine with handoff, Git, publication, feature-session and storage adapters.

The public value API intentionally does **not** re-export `Workflow`, `LooseActions`
or `ForceActions`: importing values must remain free of runtime initialization.
Existing callers may import execution classes from their canonical implementation
modules. Deprecated `apatch_lib.workflow`, `apatch_lib.loose`, etc. paths remain
identity-preserving aliases, including module-scoped mock/patch targets.

## Safety and effects

LOOSE is the default and allows manual edits, multiple ZIPs per commit and
deferred publication. STRICT keeps phase gates; FORCE is recovery and must never
force-push. Numeric operation IDs, mnemonic operations, `opSeq`, explicit
follow-ups, checkpoint updates, review/CI requirements and remote uncertainty
semantics are unchanged by the module relocation.

Only an authorized lifecycle operation may mutate Git, state or remote resources.
The engine delegates ZIP inspection/extraction to `mo_handoff`, verification to
`mo_verification`, Git inspection to `mo_git`, remote publication to
`mo_publication`, and durable state to `mo_storage`. No new persisted JSON schema
or CLI argument is introduced by R5. `skipApproves=true` removes prompts, not
eligibility, drift, branch, ZIP or publication safety checks.

## Compatibility and verification

Legacy `mo_core` value aliases and legacy root engine-module names remain shared
objects; no second class definitions or copied mutable state are created.
Maintain the same patchable module globals for existing integrations and tests.

Relevant tests include `tests/test_r5_workflow_ownership.py`,
`tests/test_workflow_domain_boundaries.py`, `tests/test_modes.py`,
`tests/test_sequences.py`, `tests/test_planner.py`, `tests/test_macros.py`,
`tests/test_guarded_commit.py`, `tests/test_check_gate.py` and the opt-in
characterization workflow/recovery suite.
