# SDD Rules for Coding Agents

These instructions apply to `docs/specs/` and its descendants. The
[human-facing index](README.md) lists active and archived work; the repository
[AGENTS.md](../../AGENTS.md) defines general engineering rules. This file is
the authoritative agent policy for specification and implementation-plan
ownership and lifecycle.

## Ownership and file layout

1. Each selected sub-specification owns one flat directory
   `docs/specs/active/<scope>/` with exactly these SDD artifacts:
   `subspec.md` (normative workstream requirements), `impl_plan.md`
   (short advisory integration/dependency map), and one matched pair
   `task_<nn>_<slug>.md` / `task_impl_plan_<nn>_<slug>.md` per task.
   No nested `tasks/`, `subspecs/`, or `implementation_plans/` directories.
2. Each task has a stable normative stage ID and acceptance oracles. The
   task document owns WHAT is required; its implementation plan owns HOW,
   with concrete verified source paths, interfaces, test inventory, negative
   cases and recovery. Do not duplicate complete requirements in plans or
   keep a second normative copy in an old `active/subspecs/` location.
   Each task MUST declare exactly one `- **type:**` in its header, with
   value `GEN_CODE`, `UPD_DOCS` or `GEN_TESTS`. `GEN_CODE` owns product source,
   code-level module `contract.md` and associated interfaces. `UPD_DOCS` owns
   concise public/developer documentation but not `contract.md`. The last
   two tasks in a workstream SHOULD be `UPD_DOCS`, then `GEN_TESTS`, unless
   an explicit developer-approved exception is recorded. `GEN_TESTS` owns
   missing/new tests, maintenance of existing tests, exact coverage evidence,
   and the final canonical `CHK`; its paired plan must include concrete
   English-commented test skeletons, failure/recovery cases and commands.
   These types are task metadata; they do not run `apatch`, grant permission
   to bypass checks or automatically select a run profile.
3. Unselected draft workstreams and their paired advisory plans live under
   `docs/specs/planned/`. This is not the accepted archive: moving an
   unaccepted candidate to `planned` does not erase its code/evidence or
   assert that its implementation is missing. Resume only on explicit
   developer selection, then move the canonical pair into `active/<scope>/`
   before task-scoped work. Planning does not authorize product changes.
4. The active umbrella specification and its independent future-stage plan
   remain directly in `active/`. Accepted legacy documents remain under
   `archive/subspecs/`; after a **new-format** workstream is explicitly
   accepted, archive its entire canonical flat directory under
   `archive/workstreams/<scope>/`, preserving task IDs and links.
5. Keep all cross-references in the umbrella, other sub-specs, plans, index,
   checkpoint and README valid after every move. Never maintain parallel
   normative active, planned and archive copies of the same owner.

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
6. **Iterate the plan together with the specification.** Maintain a separate,
   linked advisory implementation plan with concrete incremental stages,
   dependencies, verified code ownership, failure/recovery handling, and
   validation evidence as required below. Revise it when research, developer
   feedback, or normative requirements change materially. Draft planning may
   proceed alongside specification review, but no provisional plan authorizes
   implementation of unapproved requirements.

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
   `selectedTaskPath` to an adjacent task file matching `stageId`. A task
   pointer is not approval, a progress inference, or permission to mutate.
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
   flat workstream directory, including every task and plan, under
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
