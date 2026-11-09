# Repository Guidance for Coding Agents

These rules govern code, tests, configuration, and documentation created or modified in the `apatch` repository. Optimize for maintainability, safe behavior, and modules that can be understood and changed independently with limited context. Keep this file about repository content, not external handoff or publication procedures.

## Source and ownership

- Read [README.md](README.md), the relevant [Architecture](docs/ARCHITECTURE.md) and [Usage](docs/USAGE.md) sections, and the owning code and tests before editing. Use verified current source; a concatenated snapshot may omit files or lag behind the installed repository.
- Identify the module that owns the behavior. Change the smallest cohesive set of files, keep unrelated behavior untouched, and update existing abstractions instead of creating parallel implementations.
- Follow the active requirements in the [SDD index](docs/specs/README.md) when applicable. Work under `docs/specs/` must also follow its [local instructions](docs/specs/AGENTS.md). Do not invent requirements or treat an implementation as acceptance of a specification.

## Architecture and module boundaries

- **High cohesion, low coupling.** Each module should own a clear responsibility and expose a small, intentional interface. Keep domain rules close to their owner; do not scatter one invariant across CLI, modes, storage, and presentation.
- **Independent change units.** Organize code so a focused change can be understood from its owning module, explicit contracts, and relevant tests without loading the entire repository. Avoid oversized functions, hidden cross-module state, and unnecessary dependencies.
- **Stable boundaries.** Depend on documented or deliberately exposed APIs, not private implementation details from another module. Avoid new deep imports into another subsystem's internals; introduce a narrow interface when repeated cross-boundary access is needed. Do not add package-level re-exports solely to satisfy a naming convention.
- **No dependency cycles.** Prefer one-way dependencies. Let `application.py`, `workflow.py`, or other designated coordinators connect subsystems rather than coupling peer domains to each other. Do not introduce a generic event bus for ordinary synchronous calls.
- **Typed contracts.** Use explicit input/output types for new or materially changed module APIs. Prefer immutable `dataclass` values, enums, `Protocol`, or validated typed mappings where appropriate. Avoid leaking unvalidated JSON dictionaries, `Any`, or storage-specific structures across stable boundaries; preserve compatibility with existing persisted formats.
- **Dependency boundaries.** Keep Git, filesystem, subprocess, and GitHub effects behind their existing owning adapters. Inject dependencies through functions or `Protocol` interfaces when this improves isolation, testing, or reuse; avoid abstraction layers with no concrete benefit.
- **Focused decomposition.** Prefer short, cohesive files and functions. Treat growth beyond roughly 300 lines as a prompt to inspect responsibilities, not as an automatic or unsafe refactor requirement. Split by behavior and contracts, not arbitrary line counts.
- **Pragmatic architecture.** Architectural cleanliness should support feature delivery, not dominate it. Prevent obvious new coupling, duplication, and brittle contracts when fixes are small and local, but do not delay functionality for ideal structure or turn a focused feature into a broad refactor. Address accumulated architectural debt in deliberately scoped redesign or refactoring work, without compromising correctness, safety, or stable interfaces.

## Reuse and readability

- **DRY with ownership.** Consolidate duplicated behavior and validation in one well-named owner when the semantics genuinely match. Do not create premature abstractions or deduplicate superficially similar but different safety rules.
- **Common helpers.** Put genuinely general-purpose reusable utilities in an appropriate shared location. Prefer existing `apatch_lib/core/` modules for shared contracts and primitives; create a focused `apatch_lib/common.py` only if actual reusable helpers justify it. Never use `common` as a dumping ground for domain logic.
- **Express intent.** Choose clear names and explicit control flow. Avoid unexplained magic numbers, magic strings, and repeated literal protocol values; use named constants or enums when they clarify meaning or prevent inconsistent behavior. Obvious local literals need no abstraction.
- **Keep complexity proportional.** Favor direct, readable solutions over speculative frameworks, unnecessary inheritance, mutable global state, and deeply nested conditionals. Make side effects and failure modes visible in function contracts.
- **Scoped errors.** Catch expected system or integration errors at the owning boundary and translate them into actionable domain errors while preserving useful causes. Do not swallow unexpected failures, expose secrets, or turn safety failures into warnings.

## Safety and compatibility

- Preserve the CLI contract, default `LOOSE` behavior, explicit `STRICT` and `FORCE` semantics, and backward compatibility for ZIP/JSON handoffs, state, history, and configurations. `FORCE` is recovery, never force push; `skipApproves=true` removes prompts, not checks.
- Treat ZIPs, paths, configuration, external output, and Git/GitHub state as untrusted until validated. Protect dirty worktrees, explicit deletions, branch/HEAD/remote identity, fast-forward publication, review/CI gates, and recovery after partial failures.
- Keep persisted state and journals atomic and locked where required. Make retries and interrupted operations safe; do not infer successful external side effects solely from a saved checkpoint.
- Keep runtime artifacts private and outside tracked source content. Bound and redact diagnostics; never persist complete canonical-check output or sensitive review evidence in ordinary logs.

## Tests and documentation

- Verify changed code using the tools available to you, including focused unit tests when feasible. Add or update regression tests for observable behavior, invalid inputs, boundary conditions, errors, and recovery; isolate external side effects in tests.
- Keep tests deterministic and representative of real contracts. Do not weaken assertions or safety checks just to make a test pass. State clearly what was verified and what remains unverified.
- Update documentation when behavior, public interfaces, configuration, or module ownership changes. Keep [README.md](README.md) concise and place details in their owning documentation files. Avoid duplicate or contradictory descriptions.
- Write all source comments, docstrings, test content, configuration comments, and software documentation in **English**. Comments should explain intent and non-obvious constraints rather than restate code.
- When modifying specifications or implementation plans, follow `docs/specs/AGENTS.md`; do not introduce speculative stages or rewrite unrelated normative requirements as part of a code change.
