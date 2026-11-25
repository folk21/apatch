---
type: Module Contract
title: CLI Module Contract
description: Pure CLI syntax and read-only inspection entry points.
---
# CLI Module Contract

`mo_cli` owns argument syntax, normalization, help text and read-only
status/audit command dispatch. `api.py` provides the supported entry points. Handoff selection belongs to
`mo_handoff.selection`, not to CLI request parsing.
The human-readable `apatch`, producer and preflight help bodies live as UTF-8
package resources in `resources/` and are loaded using `importlib.resources`.
`help_reference.py` contains only loading, operation-code interpolation and
terminal styling. Section headers and action identifiers are colored for a
capable interactive stdout; redirecting output or setting `NO_COLOR` preserves
plain text and whitespace. The same packaged resources are included by the
committed-source deployment process.

Parsing must not alter Git, project state or configuration.

Read-only inspection receives explicitly resolved repository, configuration
and recorder dependencies. Presentation is delegated to `mo_presentation`;
workflow mutations remain in the application and workflow coordinators.

Historical `apatch_lib.cli_request`, `apatch_lib.cli_inspection` and
`apatch_lib.help_reference` imports remain identity-preserving aliases.
