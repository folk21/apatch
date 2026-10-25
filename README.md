# apatch

`apatch` is a Python CLI for safely applying AI-produced ZIP patch handoffs to Git repositories, running project-defined verification, and coordinating commits, pushes, pull requests, and merges.

It supports interactive and direct actions with three execution modes: **LOOSE (default)** for incremental/manual workflows, **STRICT** for guarded phase-by-phase processing, and **FORCE** for deliberate recovery. FORCE does not force-push.

## Documentation

| Guide | Contents |
| --- | --- |
| [Installation](docs/INSTALLATION.md) | Requirements, virtual environment, initial target-repository setup |
| [Usage](docs/USAGE.md) | CLI options, action codes, modes, handoff JSON, configuration, logging, and recovery |
| [Architecture](docs/ARCHITECTURE.md) | Modules, state management, safety boundaries, and external operations |
| [Development and Testing](docs/DEVELOPMENT.md) | Running tests, contributing, and documentation ownership |
| [SDD Specification Index](docs/specs/README.md) | Draft orchestrator specification, first-priority sub-specification, plan, and lifecycle |
| [Agent Guidance](AGENTS.md) | Repository conventions for maintainers and coding agents |

## Quick start

Install the tool and its dependencies as described in [Installation](docs/INSTALLATION.md), then run the launcher **from the root of a configured target Git repository**:

```bash
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example
```

Each generated ZIP is paired with a uniquely named JSON using the same stem, for example `apatch-PATCH-2026-10-24-00-42-example.zip` and `apatch-PATCH-2026-10-24-00-42-example.json`. The handoff name is **required**. An unqualified name resolves under `downloads_dir` (`~/Downloads` by default), and explicit `.json` paths remain supported.

Examples of direct actions:

```bash
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example op=APL
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example op=CHK
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example op=CMT skipApproves=true
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example opSeq=BRN,APL,CHK,CMT,PSH skipApproves=true
```

Review unattended operations carefully: `skipApproves=true` suppresses interactive confirmations but does not bypass Git or archive safety checks. See [Usage](docs/USAGE.md) for the full behavior and precautions.

## Development status

The implementation and regression tests are available in this repository. The [orchestrator specification](docs/specs/active/spec-apatch-orchestrator.md), its [first-priority sub-specification](docs/specs/active/subspecs/subspec-01-workflow-control.md), and [implementation plan](docs/specs/plans/apatch-orchestrator-implementation-plan.md) remain **DRAFT** documents. The created-patch ordering guard and safe ZIP metadata transport (P0.3a/b), plus expedited single-handoff operation sequences (P0.4a0), are implemented. Self-contained ZIP handoffs and multi-handoff sequences remain planned. Inspect the source and tests rather than assuming every drafted feature is available.
