---
type: Development Guide
title: SDD Rules for Coding Agents
description: Specification authoring, task ownership, traceability, and acceptance rules.
---
# SDD Rules for Coding Agents

These instructions apply to `docs/specs/` and its descendants. The
[human-facing index](README.md) lists active and archived work; the repository
[AGENTS.md](../../AGENTS.md) defines general engineering rules. This file is
the authoritative agent policy for specification and implementation-plan
ownership and lifecycle.

## Ownership and file layout

1. A selected sub-spec has exactly one normative `docs/specs/active/<scope>/subspec.md`
   containing all task requirements, acceptance oracles, stable IDs, `type`, `area`,
   feature IDs, sequence and links. Keep exactly one separate advisory
   `task_impl_plan_<nn>_<slug>.md` for each task. Do not create normative
   `task_<nn>_*.md` files or a duplicating `impl_plan.md`.
2. Every task declares exactly one `type` (`GEN_CODE`, `UPD_DOCS`, `GEN_TESTS`)
   and one `area` (`CODE`, `DOCS`, `E2E_TESTS`). The task's
   normative section in `subspec.md` owns WHAT; its linked plan owns HOW,
   verified file paths, dependencies, algorithms, tests and recovery.
   The selected model may read another area's public contracts but must not
   edit its implementation. In projects with separate backend/frontend owners,
   split cross-area features into ordered tasks with explicit handoff contracts.
   In `apatch`, all application and CLI code belongs to `CODE`; there is
   no separate frontend source area.
3. For this repository, `CODE` owns Python application/CLI/source modules,
   their code-owned `contract.md` files and focused unit/regression tests.
   `E2E_TESTS` owns cross-component integration/E2E tests, verification scripts
   and final canonical CHK. Existing test files can mix granularities: assign
   individual functions to the task's owner and do not silently rework the
   other area. `DOCS` owns general user/developer documentation and SDD
   navigation, not source contracts. No task is authorized to edit a second
   area's implementation merely because a test fails.
4. Adopt **Incremental Tests, Final Verification**: `GEN_CODE` implements and
   executes focused regressions for security, recovery, bug fixes and stable
   contracts when changing those behaviors. Exploratory tests can be deferred
   with an explicit gap recorded for final reconciliation. The penultimate
   task is `UPD_DOCS`/`DOCS`; the last is `GEN_TESTS`/`E2E_TESTS`, covering
   the complete requirement-to-test matrix, missing end-to-end tests, full
   canonical CHK, and final revision evidence. Missing CODE-owned unit coverage
   or an implementation defect discovered at the end reopens the CODE task and
   requires a fresh final check. No skipped or invented PASS is accepted.
5. Maintain stable `feature_id` references from
   [`docs/FEATURES.md`](../FEATURES.md),
   [`feature-cross-ref.yaml`](feature-cross-ref.yaml) and its schema. A feature
   can span tasks and areas; a task cannot. Cross-reference entries include
   real spec paths, stages, owning code and existing tests; use `planned`,
   `partial`, `verified` conservatively. `verified` must not be mistaken for
   developer acceptance. Feature IDs are documentation identity and must not
   be silently added as mandatory runtime ZIP/checkpoint fields.
6. Unselected drafts and plans live in `docs/specs/planned/`, not the accepted
   archive. When explicitly selected, move the canonical documents into the
   active workstream. Accepted legacy records stay under `archive/subspecs/`;
   new-format accepted workstreams move in full to
   `archive/workstreams/<scope>/` only upon developer confirmation. Preserve
   stage IDs, feature references, and links during moves.
7. The single umbrella specification is `docs/specs/umbrella_spec_apatch.md`.
   It owns project-wide goals, roadmap and invariants and has no umbrella
   implementation plan. Each selected sub-specification owns its normative
   tasks and separate advisory task implementation plans. Task types/areas
   are SDD metadata; they do not execute `apatch` or authorize product
   changes, merges or acceptance.

## Iterative specification design and implementation planning

1. **Review and approve the specification before implementation.** Treat
   specification authoring as an iterative design process, not a one-shot
   document generation task. Discuss scope, intended behavior, constraints,
   and acceptance criteria with the developer; obtain explicit approval of
   the specification as the implementation baseline. Approval of a proposed
   design is separate from acceptance of completed implementation work.
2. **Refine requirements through feedback.** Start with the developer's goals
   and verified product context, make assumptions and unresolved questions
   visible, and revise the draft in reviewable increments. Do not silently
   turn a first suggestion into a normative decision or present it as the
   only reasonable solution. Preserve developer decisions across revisions.
3. **Research comparable solutions when useful.** For uncertain workflows,
   interfaces, or product behavior, examine relevant existing applications,
   UI patterns, APIs, and prior solutions. Compare what works and what does
   not, record evidence and applicability, and use findings to propose
   improvements to the specification's UI or logic. Do not copy designs
   blindly or require external research for straightforward changes.
4. **Treat the implementation plan as engineering research.** Inspect the
   verified codebase and its contracts before selecting an architecture.
   Explore plausible algorithms, module boundaries, storage approaches,
   libraries, and integration patterns; consider alternative languages or
   stacks when that choice is genuinely open. Compare options on safety,
   correctness, recovery, performance, portability, testability, maintenance,
   and implementation complexity. Validate material assumptions with focused
   research or prototypes when warranted.
5. **Discuss consequential choices.** Present meaningful alternatives,
   trade-offs, and a reasoned recommendation to the developer before fixing
   high-impact architectural, interface, dependency, or migration decisions
   in the plan. Leave unresolved choices explicitly provisional. Do not
   assume the model's first implementation plan is uniquely optimal, and
   avoid prolonging design discussions over low-impact details.
6. **Iterate sub-spec task plans together with their requirements.** For
   each scoped sub-specification task, maintain a separate linked advisory
   implementation plan with concrete incremental stages,
   dependencies, verified code ownership, failure/recovery handling, and
   validation evidence as required below. Revise it when research, developer
   feedback, or normative requirements change materially. Draft planning may
   proceed alongside specification review, but no provisional plan authorizes
   implementation of unapproved requirements.

## Open Knowledge Format front matter

All repository Markdown documents begin with a YAML front matter block as used by the project documentation: `type`, `title`, and `description`. The heading and body remain authoritative for human-readable requirements. Keep these metadata fields synchronized with the content and repair relative links when moving documents.

Umbrella and sub-specifications declare `type: Specification`, `document_role: umbrella|subspec`, and a conservative `spec_status`. A sub-spec declares a relative `parent` pointing to the umbrella; the umbrella has no `parent` and no implementation plan. Standalone sub-spec plans declare `type: Implementation Guide`, `document_role: implementation_plan`, and a parent pointing to the owning sub-spec.

Each advisory `task_impl_plan_XX_*.md` declares `type: Implementation Guide`, `document_role: task_plan`, `parent: subspec.md`, `spec_status`, `plan_status: advisory`, `task_id`, `task_type`, `area`, `rtype`, and `feature_ids` in front matter. Valid task combinations in this code-only CLI are `GEN_CODE/CODE`, `UPD_DOCS/DOCS`, and `GEN_TESTS/E2E_TESTS`. Proposed `rtype` is `DEVELOP` for normal tasks and `ACCEPT` for final acceptance tests. These are SDD labels only, not supported `apatch` CLI runtime options. Task headers must agree with the normative task sections and the feature catalog; do not infer completion or acceptance from metadata.

Run `python3 tools/specs/validate_docs.py` with `python3 tools/specs/validate_state.py` and `python3 tools/specs/validate_features.py` after modifying specifications, plans, or document headers.

## SDD processing and evidence

1. Inspect the current source, tests, repository/worktree revision, owning
   sub-specification, its plan, and `STATE.json` before substantive staged work.
   A historical source dump is not proof of installed behavior.
2. An explicit `GENSPEC` task authorizes creating or updating the normative
   requirements and advisory plan. Include stable stage IDs, dependencies,
   source ownership, verifiable acceptance criteria, per-file implementation
   steps, migration and recovery rules, positive/negative tests, commands,
   and unresolved decisions. Mark unverified details provisional.
3. An explicit implementation task authorizes only the selected task/stage.
   Implement, test, and hand off evidence; do not treat a ZIP, merged PR,
   passing test, or completed stage as acceptance of an entire sub-spec.
4. An explicit REVIEW task is findings-only unless changes are also
   requested. Before suggesting completion, review all acceptance criteria,
   code and tests, cross-stage compatibility, recovery, and remaining risks.
5. `STATE.json` is a Git-tracked **processing checkpoint**, not the
   target-local `.apatch/apply_patch.state.json`. Validate it with
   `python3 tools/specs/validate_state.py`. `mode: SINGLE` has exactly one
   selected workstream in `active/<scope>/`, and may contain a
   `selectedTaskId` matching the corresponding task section in `subspec.md`
   and a safe existing advisory plan. A task pointer is not approval, a progress inference, or permission to mutate.
   Planned workstreams must not occur in the active checkpoint. The
   active stage ID remains stable across file moves.
6. Allowed phases are `DESIGN`, `READY_FOR_IMPLEMENTATION`,
   `READY_FOR_REVIEW`, `AWAITING_DEVELOPER_DECISION`, `BLOCKED`, `PAUSED`,
   and `ON_HOLD`. There is no `DONE` or `ACCEPTED` phase. Update the checkpoint
   **only at a developer-directed stage boundary**, never as a runtime side
   effect or to conceal failing validation. Missing/invalid state is an error.

## Documentation concision

Keep `README.md`, `docs/USAGE.md` and `docs/ARCHITECTURE.md` short, clear and
sufficiently complete for their intended readers. Do not append historical
release notes, copied specifications, implementation diaries or per-task
acceptance logs. Link to owning `api.py`, `contract.md`, selected task plans
and Git history instead of duplicating them. Treat module `contract.md` as
code-owned and maintain it during `GEN_CODE`, not in the final documentation
synchronization task. When a guide becomes obsolete, move its essential
current instructions into the owning guide and repair links before removal.

## Completion, handoff, and archival transition

1. A sub-specification is ready for completion only when **all of its scoped
   requirements and acceptance criteria** have been implemented and verified.
   Completion of one stage never implies completion of the entire sub-spec.
2. The developer is the acceptance authority. An explicit developer
   confirmation that all items of an identified sub-specification are done
   counts as acceptance of that completed scope. Do not infer acceptance
   from checks, source presence, or an agent's own assessment.
3. **Immediately after explicit acceptance**, archive the selected complete
   flat workstream directory, including `subspec.md` and every task plan, under
   `archive/workstreams/<scope>/`. Legacy accepted work remains in
   `archive/subspecs/`. Never treat moving a draft into `planned` as
   acceptance. Change `STATE.json` only after explicit successor selection.
4. If a plan is shared across sub-specifications, first split each owner's
   stages into one canonical companion, retaining future unaccepted proposals
   with their active owner. Never archive a shared plan while it still owns
   active work. Do not duplicate hundreds of lines in parallel live plans.
5. Update both README indexes, the umbrella's links, dependent specs/plans,
   and the applicable state checkpoint at the same transition. Run the
   validator and tests, and check relative Markdown links.
6. Other unfinished, unselected workstreams remain in `planned/` until
   explicitly selected. Archiving one owner does not accept others.
7. Preserve historical stage/task IDs and evidence in archived documents; clearly
   label their acceptance date and scope. Archive the umbrella only after a
   separate explicit acceptance of its own completed scope.

Do not silently promote, archive, or rewrite a partially verified sub-spec.
Developer acceptance and normative requirements outrank advisory plans.