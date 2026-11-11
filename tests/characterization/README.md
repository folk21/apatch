# Opt-in system characterization gate

This suite protects observable `apatch` behavior before module-boundary refactoring.
It is **not** an internal API compatibility suite: implementation symbols,
private imports, and file layout may change while public behavior remains stable.
The tests use disposable local Git repositories and bare remotes. They must not
mutate a developer's checkout or call real GitHub APIs.

## Running the gate

From the repository root:

```bash
sh ./run_characterization.sh focused
sh ./run_characterization.sh full
```

`focused` runs the `tests/characterization/char_*.py` modules through the
isolated, bounded `tests.timeout_runner`; it currently contains **33 cases**.
`full` runs `sh ./run_rare_checks.sh` first, followed by those 33 cases. A
failure in either part fails the gate. The existing `run_tests.sh` and
`run_rare_checks.sh` do **not** discover the extra tests: the new modules have
a `char_` prefix rather than `test_`.

The regular checks should run during routine development. Run the optional
`focused` suite for affected cross-subsystem changes, and `full` before and
after each architectural module-migration increment. Record the test result,
operating system, Python version, source SHA, and any unavailable tooling.
Passing this gate does not replace review/CI requirements or developer approval.

## Public capability coverage matrix

| Capability | Optional characterization | Existing regression evidence in `run_rare_checks.sh` | Remaining independent validation |
| --- | --- | --- | --- |
| CLI grammar, modes, help, invalid arguments | `char_cli_contracts.py` | `test_config_cli`, `test_cli_boundaries`, `test_help_reference`, `test_modes` | Current CLI examples on macOS |
| Self-contained ZIP identity and extraction | `char_workflows.py`, `char_archive_guards.py` | `test_handoffs`, `test_validation`, `test_safety` | Exhaustive hostile ZIP corpus |
| Tracked deletions, unsafe members and metadata | `char_archive_guards.py` | `test_artifact_packaging`, `test_safety`, `test_handoffs` | Fault-injected filesystem crashes |
| Branch creation, HEAD, manual edits and strict gates | `char_workflows.py`, `char_recovery.py`, `char_producer_review.py` | `test_branches`, `test_guarded_commit`, `test_modes` | macOS filesystem and Git behavior |
| Explicit branch selection and follow-up ZIPs | `char_destination.py`, `char_recovery.py` | `test_branch_reassignment`, `test_handoffs`, `test_session_continuation` | Real merged-PR and alternate-branch scenarios |
| ZIP resume, cache, state and history | `char_recovery.py`, `char_workflows.py` | `test_cache_recovery`, `test_zip_resume`, `test_history`, `test_operation_journal` | Process-interruption matrix |
| LOOSE goals, sequencing and macros | `char_workflows.py`, `char_recovery.py` | `test_planner`, `test_feature_sessions`, `test_sequences`, `test_macros` | Multiple manual-edit sequences |
| FMT, CHK and source verification | `char_workflows.py`, `char_producer_review.py` | `test_formatting`, `test_guarded_commit`, `test_artifact_preflight` | Toolchain-specific checks |
| Producer discover/preflight/ZIP packaging | `char_producer_review.py` | `test_artifact_preflight`, `test_artifact_packaging` | Parallel producer runs |
| REV opt-in, required review and evidence integrity | `char_producer_review.py` (negative admission) | `test_code_review`, `test_review_normalizer`, `test_review_context`, `test_review_evidence_api` | Actual external provider integration |
| Review retention and export | Existing regression suite | `test_review_retention`, `test_code_review` | Crash recovery and macOS no-follow behavior |
| Push, PR, CI, merge and remote uncertainty | `char_producer_review.py` (local strict gate) | `test_github`, `test_publication_goals`, `test_remote_macros` | Actual GitHub integration with human approval |
| Audit and reconciliation | `char_workflows.py` | `test_audit`, `test_audit_rules`, `test_history`, `test_operation_journal` | Large history and remote limit boundaries |
| Configuration, migrations and cross-project progress | Existing regression suite | `test_config_cli`, `test_progress`, `test_operation_journal`, `test_cache_recovery` | Real existing-user migration corpus |
| Cross-platform subprocess safety | Existing regression suite | `test_timeout_reporting`, `test_code_review`, `test_safety` | macOS/Python 3.15 execution |
| SDD state and links | Existing regression suite | `test_spec_state`; `tools/specs/validate_state.py` | Developer approval of SDD transition |

The columns intentionally distinguish **coverage present in source** from
**coverage independently exercised here**. An existing test named in this
matrix must be checked against the current repository before relying on it.
The matrix is a capability inventory, not a claim that every path or failure
interleaving is exhaustively proven.

## Invariants added in the second testing increment (T2)

- Invalid repository name, patch filename, base SHA, self-hash metadata,
  duplicate archive members, symlink members, and unsafe deletion paths must
  fail without modifying the project source or applied history.
- A legitimate tracked deletion is applied on the feature branch, while the
  original ZIP bytes and base HEAD remain unchanged.
- Applying a second ZIP to unfinished work requires explicit follow-up;
  successful follow-up retains both patch identities in state and history.
- Explicit `featureBranch` redirects the destination only; the embedded
  identity, source branch and archive SHA remain available for audit.
- Corrupt persisted state and a missing cache cannot authorize replay or
  destructive recovery.
- A producer discovers changed source without publishing, verifies the exact
  source HEAD, creates a standard ZIP, and refuses omitted changed files.
- An independently packaged ZIP can be consumed without repacking, committing
  or publishing it during `APL,BRN,CHK,STS`.
- `REV` without configured reviewers cannot authorize a commit. In `STRICT`,
  remote publication cannot skip the required local lifecycle phases.

## Required evidence before R1/R2

1. Run the `focused` suite and `full` gate against the **current complete**
   repository checkout. A concatenated source snapshot may omit launchers,
   configuration and generated state; recreate only test fixtures, never
   silently substitute an older implementation for the current checkout.
2. Run canonical checks and compare Linux and macOS results. Preserve actual
   failures, timeouts and non-repeatable errors as explicit findings.
3. Review each major public capability and safety boundary, including
   unimplemented or missing negative scenarios, against current code and
   the active normative specification.
4. Approve module boundaries and public `contract.md` interfaces in a
   separate specification and linked implementation plan before moving code.
   Map feature/stage IDs to owning APIs and tests using verified symbols.
5. During R2-R4, use the same gate as a regression baseline, not as
   authorization to weaken validation or rewrite old tests to match bugs.

**Current limitation:** Characterization tests cover a representative, broad
cross-subsystem baseline, not mathematical completeness. No macOS or real
GitHub run can be inferred from Linux synthetic fixtures. Some version-specific
scenarios require the already implemented upfront `featureBranch` capability;
verify it is present in the installed `apatch` before treating such failures
as a regression.
