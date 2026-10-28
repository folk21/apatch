# SDD Rules for Coding Agents

These instructions apply to `docs/specs/` and its descendants. The
[human-facing index](README.md) lists active and archived work; the repository
[AGENTS.md](../../AGENTS.md) defines general engineering rules. This file is
the authoritative agent policy for specification and implementation-plan
ownership and lifecycle.

## Ownership and file layout

1. Each active normative sub-specification lives at
   `docs/specs/active/subspecs/subspec-XX-<topic>.md`.
2. Its **single active advisory plan** lives directly in `docs/specs/active/`
   as `subspec-XX-<topic>-implementation-plan.md`. Do not create or use
   `docs/specs/plans/` or `docs/specs/active/plans/`.
3. The umbrella specification and its independent future-stage plan remain
   directly in `active/`. A future capability must receive its own sub-spec
   before any implementation is authorized.
4. Accepted sub-specifications and their individual plans live together in
   `docs/specs/archive/subspecs/`, preserving exactly one canonical copy of
   each file. No archived normative spec or plan remains in an active location.
5. Keep links between the owner, its plan, the umbrella, dependent specs,
   README, and processing checkpoint valid after every move or rename. Plans
   must not silently acquire normative authority.

## SDD processing and evidence

1. Inspect the current source, tests, repository/worktree revision, owning
   sub-specification, its plan, and `STATE.json` before substantive staged work.
   A historical source dump is not proof of installed behavior.
2. An explicit `GENSPEC` task authorizes creating or updating the normative
   requirements and advisory plan. Include stable stage IDs, dependencies,
   source ownership, verifiable acceptance criteria, per-file implementation
   steps, migration and recovery rules, positive/negative tests, commands,
   and unresolved decisions. Mark unverified details provisional.
3. An explicit implementation task authorizes only the selected stage.
   Implement, test, and hand off evidence; do not treat a ZIP, merged PR,
   passing test, or completed stage as acceptance of an entire sub-spec.
4. An explicit REVIEW task is findings-only unless changes are also
   requested. Before suggesting completion, review all acceptance criteria,
   code and tests, cross-stage compatibility, recovery, and remaining risks.
5. `STATE.json` is a Git-tracked **processing checkpoint**, not the product's
   target-local `.apatch/apply_patch.state.json`. Validate it with
   `python3 tools/specs/validate_state.py`. `mode: SINGLE` has exactly one
   selected focus; other active workstreams remain `ON_HOLD`. The checkpoint
   tracks only active sub-specifications and their current stage IDs.
6. Allowed phases are `DESIGN`, `READY_FOR_IMPLEMENTATION`,
   `READY_FOR_REVIEW`, `AWAITING_DEVELOPER_DECISION`, `BLOCKED`, `PAUSED`,
   and `ON_HOLD`. There is no `DONE` or `ACCEPTED` phase. Update the checkpoint
   **only at a developer-directed stage boundary**, never as a runtime side
   effect or to conceal failing validation. Missing/invalid state is an error.

## Completion, handoff, and archival transition

1. A sub-specification is ready for completion only when **all of its scoped
   requirements and acceptance criteria** have been implemented and verified.
   Completion of one stage never implies completion of the entire sub-spec.
2. The developer is the acceptance authority. An explicit developer
   confirmation that all items of an identified sub-specification are done
   counts as acceptance of that completed scope. Do not infer acceptance
   from checks, source presence, or an agent's own assessment.
3. **Immediately after acceptance, and before starting a new sub-specification,**
   move the completed sub-specification **together with its entire advisory
   implementation plan** to `archive/subspecs/`. Remove its active
   `STATE.json` workstream; if it was selected, obtain an explicit successor
   focus. Never leave the plan in `active/` after its spec is archived.
4. If a plan is shared across sub-specifications, first split each owner's
   stages into one canonical companion, retaining future unaccepted proposals
   with their active owner. Never archive a shared plan while it still owns
   active work. Do not duplicate hundreds of lines in parallel live plans.
5. Update both README indexes, the umbrella's links, dependent specs/plans,
   and the applicable state checkpoint at the same transition. Run the
   validator and tests, and check relative Markdown links.
6. Existing concurrently active, unfinished sub-specifications may remain
   active. Archiving a newly accepted sub-spec does not imply accepting or
   archiving any unrelated unfinished one.
7. Preserve historical stage IDs and evidence in archived documents; clearly
   label their acceptance date and scope. Archive the umbrella only after a
   separate explicit acceptance of its own completed scope.

Do not silently promote, archive, or rewrite a partially verified sub-spec.
Developer acceptance and normative requirements outrank advisory plans.
