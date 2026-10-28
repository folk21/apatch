# APATCH-PLAN-001 — Orchestrator Future Work

**Status:** ADVISORY / DRAFT. These are later umbrella proposals, not implementation authorizations.

**Specification:** [APATCH-SPEC-001](spec-apatch-orchestrator.md).

**Accepted historical stage plans:** [SUB-001 P0](../archive/subspecs/subspec-01-workflow-control-implementation-plan.md), [SUB-002 P1.1–P1.2](../archive/subspecs/subspec-02-state-history-audit-implementation-plan.md). The original shared PLAN-001 was separated when these sub-specifications were accepted on 2026-10-28.

## Future P1 — Further capabilities requiring dedicated sub-specifications

**Additional P1 format-adapter work (separate future sub-spec):** design and implement secure Git-native patch ingestion without changing the existing ZIP contract. Inspect the current archive/application modules, define a format-aware handoff validator, preflight via safe Git patch applicability checks, preserve manual worktree changes and deferred commits, and add cases for renames, deletions, binaries, malicious paths, conflicts, retries, and both `git diff` and `git format-patch` input forms. Do not implement until its dedicated sub-spec establishes accepted syntax and safety policy.

### P1.3 — Scheduled check adapters (future dedicated sub-spec required)

1. Define check contract and argv adapter; migrate configured canonical checks behind a compatibility facade without changing their behavior.
2. Add trigger policies for each action, after every N patches, accumulated file/byte thresholds, and elapsed intervals. Persist last-run evidence and skip reasons.
3. Add targeted/unit, lint/static, security, integration/E2E/UI/load check classes, with project-configured timeouts and blocking rules.

**Verification:** tests for scheduling thresholds, stale evidence, mandatory versus advisory failures, command failures/timeouts, and output redaction.

## P2 — Repository health and SDD stage tracking

1. Introduce a versioned evidence record keyed by repository/branch/HEAD, with `UNKNOWN`, `HEALTHY`, `DEGRADED`, and `BLOCKED` states.
2. Define optional spec/stage identity metadata and explicit completion criteria; trigger expanded checks at declared final milestones.

**Verification:** drift/revision invalidation, unknown-check semantics, stage completion guard, migration and concurrency tests.

## P3 — Independent review and plugin extensions

1. Add an external-review adapter with explicit endpoint/CLI choice, budget, cooldown, patch-size thresholds, and data redaction.
2. Add registration of independent check adapters and structured reports without growing the core `Workflow` class.

**Verification:** mocked HTTP/CLI adapters, timeout/rate-limit/retry behavior, budget enforcement, opt-out defaults, and no covert network calls.

## Progress and rollback policy

The current stage remains `GENSPEC / DRAFT` until the developer approves it. Each implementation stage SHALL leave a separately testable handoff. A failed or partial Git/GitHub action is reconciled against live state; no automated force-push, hard reset, or rollback of user work is permitted.
