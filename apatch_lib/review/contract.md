# Review module contract (initial model extraction)

## Current public API

`review.api` exports immutable `ReviewProvider` and `ScannerPolicy` models.
The historical `model.ReviewProvider` and `model.ScannerPolicy` imports
reference the same classes. These DTOs perform no filesystem or network I/O.

## Deferred scope

Review execution, normalization, evidence storage, context and retention
still live in the existing `review_*` and `code_review` modules. They must
move behind a reviewed, narrow `review.api` interface in R4. This document
records the implemented value-object slice only, not a completed review
service migration.
