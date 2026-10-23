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
| [SDD Specification Index](docs/specs/README.md) | Specification lifecycle; active specs will be added in a later stage |
| [Agent Guidance](AGENTS.md) | Repository conventions for maintainers and coding agents |

## Quick start

Install the tool and its dependencies as described in [Installation](docs/INSTALLATION.md), then run the launcher **from the root of a configured target Git repository**:

```bash
/path/to/apatch/apatch.sh
```

The default handoff is `~/Downloads/<project>_patch_params.json`. An explicit handoff JSON path is also supported.

Examples of direct actions:

```bash
/path/to/apatch/apatch.sh op=APL
/path/to/apatch/apatch.sh op=CHK
/path/to/apatch/apatch.sh op=CMT skipApproves=true
```

Review unattended operations carefully: `skipApproves=true` suppresses interactive confirmations but does not bypass Git or archive safety checks. See [Usage](docs/USAGE.md) for the full behavior and precautions.

## Development status

The implementation and regression tests are available in this repository. The SDD documentation structure is being introduced incrementally; **no active normative specification has been adopted yet**. See the [specification index](docs/specs/README.md).
