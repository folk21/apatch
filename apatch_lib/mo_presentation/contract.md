---
type: Module Contract
title: Presentation Module Contract
description: Terminal output and action-result rendering without owning state transitions.
---
# Presentation Module Contract

`mo_presentation` owns terminal coloring, workflow menu output, action-result
formatting and status display. It does not own Git state, check authorization,
archive extraction, durable records or remote publication.

`status.py` renders the read-only `PatchStatus` data supplied by the root
`status.py` evidence inspector. Legacy `apatch_lib.console` continues to
resolve to `mo_presentation.console`, and the root status rendering functions
remain callable for compatibility.
