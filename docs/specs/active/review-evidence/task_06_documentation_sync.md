# RE-06 — Documentation Synchronization (Draft Task)

- **type:** `UPD_DOCS`.
- **Task ID:** `RE-06`.
- **Status:** DRAFT / NOT STARTED; developer approval required before implementation.
- **Sub-spec:** [APATCH-SUB-006](subspec.md).
- **Task plan:** [Implementation plan](task_impl_plan_06_documentation_sync.md).
- **Dependencies:** [RE-01–RE-05](impl_plan.md) implementation reviewed; RE-05 acceptance remains a separate developer decision.

## Required outcome

Synchronize concise, accurate human-facing descriptions of the review evidence pipeline with verified behavior. This is the penultimate task; its output should allow a developer to understand configuration, privacy and recovery without reading historical implementation notes.

## Normative requirements and acceptance oracles

**RE-06-A — Current behavior.** Review `README.md`, `docs/USAGE.md`, `docs/ARCHITECTURE.md`, `docs/INSTALLATION.md` and `docs/specs/README.md` only for relevant public or architectural behavior. Update stale descriptions and links, avoiding duplicate explanations. Do not add a new guide unless an existing owner is demonstrably unsuitable.

**RE-06-B — Correct ownership.** Public settings and user commands belong to `docs/USAGE.md`; data flow, evidence trust, no-follow file access and retention/recovery boundaries belong to `docs/ARCHITECTURE.md`. Module-specific `contract.md` is a code-owned API contract and SHALL be updated in the relevant `GEN_CODE` task, not here.

**RE-06-C — Truthful security and scope.** Distinguish default-disabled evidence capture/retention, explicit consent for content disclosure/export, recorded data from live GitHub evidence, and unsupported model tool-call routing. Preserve warning that configured reviewers run with the user's OS permissions. Do not assert implementation acceptance from a passing test, and do not claim automatically executed network calls when no such integration exists.

**RE-06-D — Small and verifiable.** Check repository-relative Markdown links, existing file references, command examples and configuration keys against verified code. Remove stale progress narration and obsolete duplication. A reviewer SHALL be able to identify which document owns each current contract without consulting archival material.

## Non-goals

- No review runtime, public API, Git/GitHub, or test behavior changes.
- No edits to module `contract.md`, source docstrings or configuration defaults.
- No new publication behavior, no acceptance of SUB-006 and no deployment.

## Acceptance evidence

A scoped documentation diff, link/path check and explicit list of any unresolved source-document mismatches. RE-07 subsequently verifies documentation-dependent CLI/config assertions as part of the final check.
