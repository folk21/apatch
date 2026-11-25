---
type: Module Contract
title: Presentation Module Contract
description: Terminal output and action-result rendering without owning state transitions.
---
# Presentation Module Contract

`mo_presentation` owns approval context (`confirmation.py`), terminal coloring,
workflow menu output, action-result
formatting and status display. It does not own Git state, check authorization,
archive extraction, durable records or remote publication.

`status.py` renders `PatchStatus` evidence owned by `mo_workflows.status`.
The canonical presentation API is `mo_presentation.status`; workflow identity
and Git evidence do not depend on terminal rendering. Deprecated
`apatch_lib.console` remains an identity-preserving alias of
`mo_presentation.console`, but the deleted root `status.py` has no facade.
