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
| [Security and Recovery](docs/SECURITY.md) | ZIP trust boundaries, checks, partial failures, and platform support |
| [SDD Specification Index](docs/specs/README.md) | Draft orchestrator specification, first-priority sub-specification, plan, and lifecycle |
| [Agent Guidance](AGENTS.md) | Repository conventions for maintainers and coding agents |

## Quick start

Install the tool and its dependencies as described in [Installation](docs/INSTALLATION.md), then run the launcher **from the root of a configured target Git repository**:

```bash
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example
```

New ZIPs embed `<repository>/.apatch/params.json`; no separate JSON download is needed. The first action is `APL`, followed by `BRN`; subsequent commands use the verified project-local cache. Legacy `.json` handoffs remain supported.

Examples of direct actions:

```bash
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example opSeq=APL,BRN,CHK,CMT,PSH,STS skipApproves=true
/path/to/apatch/apatch.sh opSeq=APL,BRN,APL,CHK,CMT,PSH,STS handoffSeq=first.zip,second.zip skipApproves=true
```

`skipApproves=true` suppresses confirmation, **not** safety checks; canonical project checks execute code with your normal user permissions. Review ZIPs before unattended publication. See [Usage](docs/USAGE.md) and [Security](docs/SECURITY.md).

## Development status

The implementation and regression tests are available in this repository. The [orchestrator specification](docs/specs/active/spec-apatch-orchestrator.md), its [first-priority sub-specification](docs/specs/active/subspecs/subspec-01-workflow-control.md), and [implementation plan](docs/specs/plans/apatch-orchestrator-implementation-plan.md) remain **DRAFT** documents. Created-patch ordering and ZIP metadata transport (P0.3a/b), self-contained ZIPs with cached handoffs and an apply-first path (P0.3c), sequenced operations with console outcomes (P0.4a), and explicit multi-ZIP LOOSE sequences (P0.4b) are implemented. Numeric `2 [BAP]` is deprecated for self-contained workflows but remains available for explicit legacy JSON handoffs until their migration is complete.
