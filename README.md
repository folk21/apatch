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
| [SDD Specification Index](docs/specs/README.md) | Active and accepted sub-specifications, plans, and processing checkpoint |
| [Agent Guidance](AGENTS.md) | Repository-wide coding-agent conventions; [SDD-specific agent rules](docs/specs/AGENTS.md) |

## Quick start

Install the tool and its dependencies as described in [Installation](docs/INSTALLATION.md), then run the launcher **from the root of a configured target Git repository**:

```bash
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example
```

New ZIPs embed `<repository>/.apatch/params.json`; no separate JSON download is needed. The first action is `APL`, followed by `BRN`; subsequent commands use the verified project-local cache. Legacy `.json` handoffs remain supported.

For an unexpected repair ZIP while earlier patch changes remain uncommitted on their feature branch, use explicit LOOSE `followup=true` with the new ZIP and `APL` instead of replaying or resetting the previous patch. See [Usage](docs/USAGE.md#unplanned-repair-zip-on-an-unfinished-feature-branch-followuptrue).

To inspect recorded activity across all projects from any directory, use `apatch.sh info=PROGRESS`. This read-only summary does not require a Git repository or a handoff.

Examples of direct actions:

```bash
/path/to/apatch/apatch.sh apatch-PATCH-2026-10-24-00-42-example opSeq=APL,BRN,CHK,CMT,PSH,STS skipApproves=true
/path/to/apatch/apatch.sh opSeq=APL,BRN,APL,CHK,CMT,PSH,STS handoffSeq=first.zip,second.zip skipApproves=true
```

`skipApproves=true` suppresses confirmation, **not** safety checks; canonical project checks execute code with your normal user permissions. Review ZIPs before unattended publication. See [Usage](docs/USAGE.md) and [Security](docs/SECURITY.md).

## Development status

The implementation and regression tests are available in this repository. The [orchestrator umbrella](docs/specs/active/spec-apatch-orchestrator.md) remains a DRAFT for future capabilities; [SUB-001 — Workflow Control](docs/specs/archive/subspecs/subspec-01-workflow-control.md) and its [P0 implementation plan](docs/specs/archive/subspecs/subspec-01-workflow-control-implementation-plan.md) were accepted and archived on 2026-10-28. Created-patch ordering and ZIP metadata transport (P0.3a/b), self-contained ZIPs with cached handoffs and an apply-first path (P0.3c), sequenced operations with console outcomes (P0.4a), and explicit multi-ZIP LOOSE sequences (P0.4b) are implemented. Numeric `2 [BAP]` is deprecated for self-contained workflows but remains available for explicit legacy JSON handoffs until their migration is complete.

P0.5a records cross-project operation summaries in the installed tool's private `.apatch/progress/` directory; P0.5b adds the read-only `info=PROGRESS` overview. P1.1 adds a durable project-local operation journal with explicit attempts and outcomes. Recorded evidence is not a substitute for live GitHub status.

P1.2 adds `11 [AUD]`, an offline-by-default, read-only audit of known patch history, with explicit `verifyRemote=true` for optional remote verification. Later source increments include FS-00R deterministic ZIP resume, WM-01/WM-02 activity and base-branch improvements, and architectural separation with optional quality tooling. See [Usage](docs/USAGE.md#repository-wide-patch-audit-11-aud) for operational details.

FS-05 introduces guarded LOOSE local `goal=CHECKED|COMMITTED` execution
and read-only `planOnly=true` previews. FS-06 extends explicit goals to
`PUSHED|PR_CREATED|MERGED` with exact PR source-revision checks, safe
uncertain-outcome reconciliation and separately retryable base synchronization.
See [Usage](docs/USAGE.md#guarded-goals-goal-fs-05fs-06).

On 2026-10-28 the developer also accepted and archived [SUB-002 — Execution History and Audit](docs/specs/archive/subspecs/subspec-02-state-history-audit.md) and [SUB-005 — Architectural Simplification](docs/specs/archive/subspecs/subspec-05-architectural-simplification.md), together with their plans. [SUB-003 — Feature Sessions](docs/specs/active/subspecs/subspec-03-feature-session-planning.md) and [SUB-004 — Operational Workflows](docs/specs/active/subspecs/subspec-04-operational-workflows.md) remain active. See the [SDD index](docs/specs/README.md) for the plan mapping and the [SDD agent rules](docs/specs/AGENTS.md) for lifecycle and archiving policy. [STATE.json](docs/specs/STATE.json) records only the developer-controlled processing focus and can be checked with `python3 tools/specs/validate_state.py`.
