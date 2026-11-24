---
type: Module Contract
title: CLI Module Contract
description: Pure CLI syntax and read-only inspection entry points.
---
# CLI Module Contract

`mo_cli` owns argument syntax, normalization, help text and read-only
status/audit command dispatch. `api.py` provides the supported entry points.
Parsing must not alter Git, project state or configuration.

Read-only inspection receives explicitly resolved repository, configuration
and recorder dependencies. Presentation is delegated to `mo_presentation`;
workflow mutations remain in the application and workflow coordinators.

Historical `apatch_lib.cli_request`, `apatch_lib.cli_inspection` and
`apatch_lib.help_reference` imports remain identity-preserving aliases.
