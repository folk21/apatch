---
type: Module Contract
title: Verification Module Contract
description: Ownership of canonical checks, optional formatting and builds, and check-boundary policy.
---
# Verification Module Contract

`mo_verification` owns `CHK`, `FMT`, `BLD`, and the existing boundary-policy
functions. `api.py` exports `run_checks`, `run_formatters`, `run_build`,
`require_boundary`, and `record_commit` for the workflow coordinator.

`run_checks(workflow)` requires an applied patch, the recorded branch and HEAD,
a matching patch identity and exact changed-path footprint. It runs `git diff
--check` and the configured canonical check commands with bounded total and
idle timeouts. Only unchanged worktree bytes are recorded as verified; a
changed result invalidates verification. Runtime command output is printed to
the console, not persisted wholesale in logs.

`FMT` and `BLD` explicitly invalidate prior CHK/REV evidence. They preserve
Git index and branch/HEAD checks, detect changed filesystem identities, and
do not create verification evidence. Build changes remain disallowed; format
changes require explicit review and a fresh `CHK`. The check-boundary policy
remains distinct from remote approval, CI, and review gates.

`workflow.py` owns admission, state persistence and action sequencing.
`mo_git/commands.py` owns subprocess execution. The legacy imports
`apatch_lib.building`, `apatch_lib.formatting`, and `apatch_lib.check_gates`
resolve to identical module objects in this package for existing callers and
patch targets. No persisted format, ZIP schema, or CLI operation is changed.

Run `tests/test_r4_verification_git.py`, `tests/test_building.py`,
`tests/test_formatting.py`, `tests/test_check_gate.py`,
`tests/test_git_command_boundaries.py`, and `tests/test_safety.py`.
