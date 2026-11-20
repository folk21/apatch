---
type: Module Overview
title: apatch
description: Introduction, quick start, documentation entry points, and current development status.
---
# apatch

`apatch` is a Python CLI for applying verified ZIP patch handoffs to Git repositories, running project-defined checks, and coordinating guarded commits, pushes, pull requests and merges. **LOOSE** is the default for manual, incremental work; **STRICT** enforces phase boundaries; **FORCE** reconciles interrupted/manual operations without force-pushing.

## Documentation

- [Installation](docs/INSTALLATION.md) — standalone deployment, local configuration and setup.
- [Usage](docs/USAGE.md) — actions, modes, project checks and operational recovery.
- [Architecture](docs/ARCHITECTURE.md) — module ownership, safety, privacy, development and tests.
- [Features](docs/FEATURES.md) — stable capability IDs and ownership links.
- [SDD specifications](docs/specs/README.md) — active tasks and plans, planned drafts, archived work and checkpoint.
- [Repository guidance](AGENTS.md) / [SDD guidance](docs/specs/AGENTS.md) — engineering and documentation rules.

## Quick start

Run from the **target Git repository**, after configuring the installed tool and its project checks as described in [Installation](docs/INSTALLATION.md):

```bash
apatch my-patch-stem opSeq=APL,BRN,CHK,STS skipApproves=true
apatch opSeq=CMT,PSH,PR,STS skipApproves=true
```

A self-contained ZIP embeds `<repository>/.apatch/params.json`; a separate JSON download is unnecessary. ZIP-first application runs `APL` before `BRN`. The verified handoff is cached for later commands. A new ZIP on an existing feature branch uses explicit `followup=true` without `BRN`; see [Usage](docs/USAGE.md#4-continue-a-feature-with-another-zip). Legacy JSON handoffs remain supported. `skipApproves=true` only skips prompts, never safety gates. Inspect generated code, configuration and staged content before unattended publication.

Use `apatch op=STS` to inspect a patch, `apatch op=AUD` for offline repository-wide audit, or `apatch info=PROGRESS` to inspect recorded tool activity. Optional format, build and independent review commands depend on project configuration; `BLD` does not replace canonical `CHK`.

## Development status

The CLI, ZIP handoff, feature-branch workflow, state/history journaling, verification, review and GitHub safeguards have automated regression coverage. Planned extensions and task-level implementation detail live in the [SDD index](docs/specs/README.md); a draft or completed test is not an acceptance or deployment claim. `SUB-001`, `SUB-002` and `SUB-005` are archived as accepted, while `SUB-003` and `SUB-004` remain unselected drafts.

`SUB-006 — Review Evidence Pipeline` is the selected draft workstream. Its checkpoint remains `RE-05 / READY_FOR_REVIEW`; the proposed final documentation and acceptance-test tasks are `RE-06 / UPD_DOCS` and `RE-07 / GEN_TESTS`. No later task or production deployment is implied by the document reorganization. Run `python3 tools/specs/validate_state.py` to validate the processing pointer; see [Architecture](docs/ARCHITECTURE.md#development-and-verification) for checks.