# RE-05 — Retention, Export and Recovery (Draft Task)

- **type:** `GEN_CODE`.
- **Task ID:** `RE-05`.
- **Status:** DRAFT / READY_FOR_REVIEW (developer acceptance pending); splitting this document does not grant implementation authorization.
- **Sub-spec:** [APATCH-SUB-006](subspec.md).
- **Task plan:** [Implementation plan](task_impl_plan_05_retention_export_recovery.md).
- **Dependencies:** [RE-04](task_04_selective_evidence_retrieval.md) (candidate implementation; acceptance not inferred).
- **Primary code owners (verified snapshot):** `apatch_lib/review_retention.py`, `apatch_lib/review_artifacts.py`, `apatch_lib/code_review.py`, `apatch_lib/configuration/loaders.py`.
- **Relevant existing tests:** `tests/test_review_retention.py`, `tests/test_code_review.py`.

## Normative requirements and acceptance oracles

The acceptance test cases below are requirements. RE-07 owns the final suite reconciliation and canonical CHK execution; task-specific security failures remain blocking during implementation. This task does not authorize bypassing existing runtime checks or publication gates.


**RE-05-A — Policy and scope.** Schema-v1 project YAML SHALL accept
`review_retention_enabled: false` (default) and bounded
`review_retention_max_runs` (1–10,000; default 100),
`review_retention_max_bytes` (1 MiB–10 GiB; default 512 MiB), and
`review_retention_max_age_days` (1–3,650; default 30). Invalid values SHALL
fail configuration loading, including boolean values supplied as integer
limits. Disabled retention SHALL never initiate an automatic deletion.
Explicit `prune_review_artifacts()` SHALL default to a non-destructive preview.
When enabled, `REV` SHALL apply retention under an exclusive project-local
lock immediately before allocating a new run; no independent scheduler is
introduced. Count and byte limits SHALL reserve space for the new run;
limits are conservative allocation checks, not guaranteed filesystem quotas.
If protected evidence prevents proving storage usage, fail closed before
starting a new reviewer process.

**RE-05-B — Protected deletion.** Retention SHALL inspect only
`<root>/.apatch/reviews/review-<24-hex>/` directories through no-follow
file descriptors. Terminal `COMPLETED` or `FAILED` manifests with recognized
provider/context files, private modes, exact member inventory and matching
SHA-256 references are eligible for pruning. Apply age, count and size rules
oldest first, with stable tie ordering. Unknown names, unexpected files,
symlinks, hardlinks, changed contents, unreadable/partial manifests, and
`STARTED` runs SHALL remain protected. No Git or checkpoint/history record is
removed. The lock file SHALL be private and no-follow; completed known runs
SHALL be removed only by explicit pruning or the explicit project retention
opt-in. A deletion journal inside each eligible run SHALL allow an interrupted
partial cleanup to complete on the next requested maintenance, after strictly
rechecking remaining members. An invalid journal or unexpected member SHALL
block further cleanup of that run. Do not infer review success from pruning.

**RE-05-C — Redacted references.** Local internal
`export_review_summary(root, review_id, consent=True)` SHALL require explicit
consent and a safe review ID. It SHALL verify the entire terminal manifest,
raw stdout/stderr sizes and SHA-256 and all indexed derivatives before
returning a deterministic UTF-8 JSON document of at most 8,192 bytes.
Export SHALL expose only a relative review reference, manifest SHA-256,
provider IDs/kinds, command exit/truncation/timeout status and completed/failed
run status. Source paths, Git snapshots, prompts, findings, raw logs, stderr,
normalization bodies, secret-bearing messages and full LLM context SHALL NOT
be exported. No transport, network call, CLI action, external model dispatcher
or automatic export is introduced. Missing or modified evidence SHALL fail
closed; this is metadata minimization, not a guarantee that user-assigned
provider IDs are semantically secret-free.

**RE-05-D — Failure and compatibility.** Interrupted captures retain
`STARTED` or `FAILED` evidence without implied PASS or automatic paid-provider
retry. Existing valid CHK and previously recorded review verdicts SHALL remain
untouched by retention. Fresh replay, retrieval or export requiring deleted
artifacts SHALL fail closed. Filesystem errors and unavailable locks SHALL
abort without modifying Git/PR state. LOOSE, STRICT, FORCE and legacy handoffs
remain unchanged.

**RE-05 acceptance:** Focused and integration tests for default preview,
count/age/size selection, project policy validation, ignored/private file
modes, concurrent lockers, unknown entries, symlink/hardlink attacks,
truncated/changed files, interruption during deletion and safe resumption,
explicit consent, absent/stale evidence, metadata-only export and CHK/REV
compatibility. Attempt regular/rare suites and checkpoint validation; report
all verification environment limitations. Developer acceptance is separate.
