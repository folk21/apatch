# RE-01 — Private Bounded Raw Evidence Capture (Draft Task)

- **type:** `GEN_CODE`.
- **Task ID:** `RE-01`.
- **Status:** DRAFT / CANDIDATE IMPLEMENTATION; DEVELOPER ACCEPTANCE PENDING; splitting this document does not grant implementation authorization.
- **Sub-spec:** [APATCH-SUB-006](subspec.md).
- **Task plan:** [Implementation plan](task_impl_plan_01_raw_evidence_capture.md).
- **Dependencies:** None.
- **Primary code owners (verified snapshot):** `apatch_lib/review_artifacts.py`, `apatch_lib/code_review.py`, `apatch_lib/configuration/loaders.py`, `apatch_lib/core/paths.py`.
- **Relevant existing tests:** `tests/test_code_review.py`, `tests/test_config_cli.py`.

## Normative requirements and acceptance oracles

The acceptance test cases below are requirements. RE-07 owns the final suite reconciliation and canonical CHK execution; task-specific security failures remain blocking during implementation. This task does not authorize bypassing existing runtime checks or publication gates.


**RE-01-A** Project schema-v1 YAML SHALL accept `review_artifacts_enabled` (boolean, default false) and `review_artifact_max_bytes` (integer 65,536–67,108,864, default 8,388,608), rejecting unknown or invalid values. Existing configs without the keys SHALL retain behavior. No implicit network/model calls are introduced.

**RE-01-B** For enabled capture, each explicit `REV` after validated CHK inputs SHALL create a unique private run directory `<root>/.apatch/reviews/review-<random>/`. Storage SHALL be ignored and untracked by Git before writing; the implementation SHALL fail closed for symlinked or otherwise unsafe storage. Directory mode SHALL be `0700`; individual files SHALL be `0600`. Persistent output is sensitive local runtime data, excluded from ZIP overlays and application logs.

**RE-01-C** External reviewer stdout and stderr SHALL be drained concurrently to separate files, without accumulating the full streams in RAM. Their **combined** bytes SHALL not exceed `review_artifact_max_bytes` per provider; exceeding the bound SHALL terminate the process group where supported, retain a truncated partial report, and fail `REV`. The configured timeout and no-source-mutation guards remain mandatory. LLM JSON parsing SHALL never consume more than the prior 262,144-byte stdout limit. Legacy capture-disabled behavior remains unchanged in RE-01.

**RE-01-D** A schema-v1 `manifest.json` SHALL record run identity, exact pre-review snapshot, status (`STARTED`, `FAILED`, `COMPLETED`), and each completed provider's ID/kind, exit status, stdout/stderr basename, byte counts, SHA-256 digests, truncation and timeout flags. It SHALL NOT store the diff, prompt, credentials, or argv. Manifests SHALL be replaced atomically and failed runs SHALL retain available evidence. A successful workflow checkpoint MAY include a relative artifact path; raw data SHALL NOT be embedded in the checkpoint.

**RE-01-E** A nonzero exit, timeout, overflow, missing/inaccessible output, malformed model JSON, or detected source/index/branch/policy drift SHALL never produce PASS. Review artifacts are diagnostics and do not authorize commit. Missing or incomplete manifests are not evidence of success.

**RE-01 acceptance:** Tests prove complete 400+ KiB scripted output capture, independent stderr, private file permissions, correct digests, failed subprocess retention and blocking, overflow and timeout blocking, symlink protection, ignored/untracked output, LLM JSON compatibility, unchanged legacy REV/CHK/CMT behavior, and no real remote actions. The regular and extended test suites and state validator SHALL be attempted before handoff; any unavailable baseline files or environments SHALL be disclosed.
