---
type: Module Contract
title: Audit module contract
description: Read-only local and remote evidence collection, audit rules, and reconciliation.
---
# Audit module contract

## Ownership and public API

`mo_audit` owns read-only audit evidence collection, pure audit rules, and
reconciliation into human-readable findings. `mo_audit.api` publishes
`audit_repository`, `format_audit`, `AuditReport`, and `Finding`.

`audit_collectors.py` observes local Git, history, state, and optionally remote
GitHub evidence through the existing publication adapter. `audit_rules.py`
interprets the observations, and `reconciliation.py` assembles the report.
This module does not apply ZIPs, change Git refs, write lifecycle state, or
replay uncertain remote mutations.

## Compatibility and dependencies

Historical `apatch_lib.audit_collectors`, `apatch_lib.audit_rules`, and
`apatch_lib.reconciliation` imports resolve to the same module objects as the
canonical `apatch_lib.mo_audit.*` modules, preserving patchable test seams.
Internal audit implementations may depend on the existing Git, state, and
publication adapters as read-only providers; later boundary migration can
narrow these dependencies without altering the public audit contract.

## Verification

Run `tests.test_audit`, `tests.test_audit_rules`, the focused module ownership
tests, and the canonical `run_tests.sh` suite. Remote activity is mocked in
regression tests; no live GitHub behavior is asserted by these checks.
