# Repository Guidance for Coding Agents

These rules apply to the entire `apatch` repository. They are implementation guidance, not a substitute for the project's public CLI contract.

## Orientation and source authority

1. Read [README.md](README.md), then the document relevant to the task: [Architecture](docs/ARCHITECTURE.md), [Usage](docs/USAGE.md), [Installation](docs/INSTALLATION.md), or [Development](docs/DEVELOPMENT.md).
2. Check the [SDD specification index](docs/specs/README.md) before implementing behavior described by a specification. Orchestrator specifications remain **DRAFT**; individual stages may already be implemented. Verify actual source behavior and tests before treating a proposed requirement as available, and do not label documentation-only work as completed behavior.
   For staged SDD work, use the index's lifecycle and validate `docs/specs/STATE.json` at developer-controlled checkpoints with `python3 tools/specs/validate_state.py`. This is a repository documentation checkpoint, never a runtime workflow state or implicit approval. Require explicit developer acceptance before archiving any sub-specification and its plan.
3. Read only the owning modules and relevant tests after identifying the behavior to change. See [Architecture](docs/ARCHITECTURE.md) for code ownership.
4. Follow newer verified repository contents over stale concatenated snapshots. A snapshot may omit files and is not necessarily a complete checkout.

## Engineering constraints

- Preserve compatibility of modes `LOOSE` (default), `STRICT`, and `FORCE`; numeric and mnemonic operations; handoff JSON; and existing state/history formats.
- Keep Git operations and archive extraction non-destructive. Never weaken validation to accommodate an unexpected state or a failing fixture.
- Maintain safe behavior under manually edited or dirty worktrees, mixed patch cycles, interrupted operations, and remote drift.
- Preserve explicit approval boundaries. `skipApproves=true` skips prompts but not safety checks; FORCE is not force-push.
- Keep project-local runtime state, locks, journals, backups, and logs inside the target repository's `.apatch/`.
- Never persist full canonical-check output to the `apatch` log. Report check progress in the console; log starts and bounded failure details.
- Avoid unrelated refactoring and new dependencies unless necessary for the requested behavior.

## Changes and tests

- Add focused regression tests for behavior changes, including failures and recovery paths.
- Use temporary local Git repositories and mocked GitHub operations; never run destructive integration tests on a real developer repository.
- Run `sh ./run_tests.sh` after each increment and `sh ./run_rare_checks.sh` before handoff or release; the extended suite includes regular tests. GitHub Actions is manual-only, so local extended checks are required before merging. If checks cannot run, record the exact limitation.
- Update documentation in its owning file. Keep README as navigation, not a duplicate of Usage or Architecture.
- Write source comments, docstrings, tests, and all project documentation in **English**.
- Do not create or update active specifications, implementation plans, or roadmap stages unless that documentation work is explicitly requested.

## Review checklist

Before handing off changes, check repository/branch selection, patch-path safety, worktree preservation, retry behavior, atomic state writes, logging privacy, backward compatibility, and whether any unverified platform-specific assumptions remain.
