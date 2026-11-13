# Proposed modular architecture for apatch

**State:** DRAFT FOR DEVELOPER REVIEW — no production migration authorized.
**Linked execution plan:** [implementation-plan.md](implementation-plan.md).
**Current implementation:** [../ARCHITECTURE.md](../../ARCHITECTURE.md).
**Previous accepted simplification:**
[SUB-005](../../specs/archive/subspecs/subspec-05-architectural-simplification.md).

## 1. Motivation, scope and constraints

The goal is a *behavior-preserving* decomposition with a minimal `core`,
module-owned models and constants, explicit public APIs, independent contracts,
and enforceable one-way dependencies. It enables narrow-context changes by
future local AI workers without turning apatch into an AI-agent orchestrator.

The inspected tree has 58 Python files below `apatch_lib/` (approximately
12,186 source lines). Prominent coupling hotspots are `loose.py` (633 lines),
`planner.py` (618), `workflow.py` (616), `force.py` (496), `model.py` (488),
`github.py` (477), and `gitutil.py` (442). File length alone is not a failure;
these files mix decisions, side effects and ownership that belong to separate
bounded contexts. In particular:

- `model.py` defines `Abort`, `Config`, review-provider models, `Handoff`,
  `load_config()`, `load_project_config()`, validation and handoff parsing.
- `core/contracts.py` mixes `WorkflowRecord`, `StateDocument`, `GitHubPr`
  and `ActionResult`, and imports `RemoteOutcomeUnknown` from `model.py`.
- `gitutil.py` combines subprocess/Git execution, worktree inspection,
  confirmation prompting and context-local approval state.
- `Workflow`, `LooseActions`, `ForceActions`, and `planner.py` coordinate
  both local Git changes and external publication outcomes.

### Compatibility invariants

Every migration MUST preserve the existing externally observable contract:

1. All action IDs and aliases `0..13`, `op`, `opSeq`, `handoffSeq`, menu,
   `goal`, `followup`, `featureBranch` and defaults; LOOSE remains default.
   `2 [BAP]` remains legacy-JSON-only/deprecated.
2. ZIP-first `APL` then `BRN`, validated ZIP schema-v1 embedded metadata,
   original ZIP digest, source/effective branch evidence, tracked deletions,
   legacy JSON handoffs, cached parameters and multi-ZIP behavior.
3. LOOSE manual edits, alternative branches, multiple patches per commit,
   deferred pushes; STRICT guards; FORCE recovery without force push.
4. Dirty worktree/index preservation, symlink/path traversal rejection,
   archive and history integrity, branch/HEAD/remote verification, verified
   commit scope, fast-forward-only publication and GitHub PR/CI/review gates.
5. Atomic/locked state, history and operation journaling; v1/v2 state
   migration, progress evidence, interruption recovery and uncertainty on
   remote writes. A recorded outcome alone cannot prove a remote mutation.
6. Project check output streams to console; logs remain bounded and
   redacted. Tests may use disposable Git and mocked GitHub only.

Refactoring is not permission to change policy, add a new user-facing mode,
rename error categories, reinterpret saved data or auto-publish code. Any
necessary behavior change requires a distinct reviewed specification and
regression evidence.

## 2. Proposed package ownership

The packages below are **target ownership boundaries**, some introduced in R2.
Each owns `api.py`, `models.py`, `constants.py` only when those files serve a
real purpose, and an English `contract.md` in the package root. Split
implementation files by capability, not by an arbitrary maximum size.

| Package | Owns | Does not own |
| --- | --- | --- |
| `core/` | Domain-neutral exception base and truly cross-domain primitive types | CLI, Git/ZIP/GitHub, workflow state, PR models, configuration or file I/O |
| `common/` | Proven reusable, pure and domain-neutral path/text/hash utilities | Validation policy, GitHub fields, workflow transitions or feature decisions |
| `configuration/` | Global/project loaders, policy validation, effective settings and source precedence | Performing configured commands or choosing workflow actions |
| `git/` | Local repository, refs, HEAD, worktree/index, subprocess, bounded Git effects | GitHub PR protocol, ZIP extraction, interactive approval policy |
| `handoff/` | ZIP/JSON input, validation, safe extraction, producer preflight/packaging, cache and patch history | Branch creation, PR merge or workflow phase decisions |
| `workflows/` | Phase/mode transitions, action results, sessions, planner, macros, checks, commits and state/journal decisions | Parsing GitHub JSON or ZIP bytes directly |
| `publication/` | GitHub protocol, PR/CI/review decisions, remote-effect reconciliation, guarded merge/sync | Feature-session state machine or ZIP details |
| `review/` | REV providers, evidence capture/normalization/lookup, retention and review policy | AI code generation, SDD task routing, GitHub approvals |
| `audit/` | Read-only reconciliation, historical findings and cross-project progress | Changing Git or publication state, approving replay |
| `runtime/` | CLI grammar/help, request dispatch, composition, presentation and logging setup | Domain decisions duplicated from owning APIs |

`storage/locking.py` remains a stable shared low-level adapter until an
independently tested storage extraction is justified. A new `common` module
must not become a generic dumping ground. Frozen DTOs and `Protocol` ports
may live in an owning module's `models.py`/`ports.py`; a domain-neutral
base exception is the only unavoidable common error ancestor.

## 3. Dependency direction and public API rule

```
        runtime (composition root, CLI, presentation)
                         |
       +-----------------+------------------+
       |                 |                  |
      audit           workflow       configuration
       |                 |
       |         +-------+------------------------+
       |         |            |          |         |
       +------> handoff       git     publication   review
                     |         ^          |
                     +---------+----------+
                         core / common
```

The diagram is conceptual, not a Python import graph. Enforceable rules:

- `runtime` may invoke every published domain API, but domain packages
  MUST NOT import `runtime`.
- `workflows` may invoke `handoff.api`, `git.api`, `publication.api`,
  `review.api`, and configuration *typed settings*; none of those packages
  may import `workflow` implementation or mutable checkpoint objects.
- `audit` may invoke **read-only** APIs of `workflows`, `handoff`, `git`, and
  `publication`; `workflows` MUST NOT depend on `audit`.
- `publication` and `handoff` may rely on narrow read/write Git ports;
  `review` should receive a read-only checked-snapshot port. The composition
  root supplies the concrete adapter. No peer can import another peer's
  private file or mutate its models.
- `configuration`, `core` and `common` have no outward dependencies on
  higher-level domain packages. `git` must not import `publication`.
- Imports of another domain's `api.py` or documented `models.py` are the
  **only** allowed cross-boundary imports; dependency injection is preferred
  when direct imports would create a cycle. Enforce the rule with an AST
  import check after each migration slice.

The plural `workflows/` avoids the import-name collision with the existing
`workflow.py` engine; the latter remains a compatibility coordinator until R5.

Stable historical imports such as `apatch_lib.model.Config` or
`apatch_lib.core.contracts.GitHubPr` may survive temporarily as **thin
compatibility re-exports**. These are explicit migration exceptions, have
owner and expiry stages, and must not reimplement validation or I/O. The
public entry points `apatch.py`, `apatch.sh`, `apatch_pack.py` and
`apatch_preflight.py` remain stable.

## 4. Models, configuration, constants and errors

- `models.py`: only dataclasses, enums, TypedDicts, immutable value objects
  and pure validation tied to a model's invariants. It must not read files,
  start processes, access Git/GitHub, create directories or load config.
- `load_config()` and `load_project_config()` move to
  `configuration/loaders.py`. ZIP parsing and handoff validation move to
  `handoff/parsing.py`; their result models live in `handoff/models.py`.
  `ReviewProvider` and `ScannerPolicy` are reviewer domain models;
  `configuration` returns neutral validated setting values and the
  `runtime` composition root maps them into review models. `Config` remains source-compatible through a deprecated import
  adapter until all callers migrate.
- Put settings with policy intent (timeouts, size limits, retry counts) in
  configuration, with strict range/combination validation *on read*.
  Keep fixed GitHub response keys, API domains, regex patterns and protocol
  field lists in their **owning domain's** constants or typed decoders.
  `https://github.com/` is a fixed protocol/validation boundary unless
  configurable GitHub Enterprise support is separately specified.
- In `github.py:_validate_pr()`, name the positive PR-number maximum, SHA
  regex, URL pattern, allowed states, and bounded nullable fields instead
  of repeating literals. A typed PR adapter should translate
  `mergedAt`/`reviewDecision`/`mergeable`/`mergeStateStatus` into documented
  semantic fields while retaining the original API names only at the
  external boundary. Do not rename wire keys in persisted evidence.
- `core` must not import `model.py`. Move workflow outcomes to
  `workflows.api`, GitHub PR DTOs to `publication.models`, and remote
  uncertainty to `publication.errors` (with historical alias).
- Avoid introducing constants for universally obvious `0`, `1`, `None`,
  string labels used once or trivial control flow. Every new constant must
  clarify a protocol invariant or an actual repeated value.

## 5. Contract format and enforcement

Every implemented domain `contract.md` SHALL document: owner and purpose;
public `api.py` operations with argument/result DTOs; allowed imports and
side effects; error/failure semantics; concurrency, state and recovery;
security invariants; existing compatibility exports; and contract tests.
Proposed APIs are detailed in [contracts](README.md#documents).

At approved migration stages, add architecture tests which:

1. Parse Python imports and fail on forbidden cross-domain imports and cycles.
2. Verify `models.py` imports and AST bodies contain no filesystem/subprocess,
   network or config-loader operations; explicit domain exceptions need review.
3. Check every implemented domain has a reachable `api.py` and colocated
   `contract.md`, and that the documented exported symbols exist.
4. Check feature IDs map to *verified* exported symbols/classes and tests.
5. Prove existing public entry points and data schemas work unchanged using
   regular, extended and opt-in characterization tests.

Do not enable an architecture gate globally until migrated domains satisfy it;
first run the gate in *report-only* mode and freeze an explicit exception
baseline. No hidden circularity exemptions or broad import allowlists.

## 6. R1 review/approval decisions

**Recommended:** eight domain packages plus a minimal core/common, implemented
through four small migration waves. Review these consequential choices before
promoting the architecture to a normative SDD sub-spec:

- **Boundary count:** eight cohesive packages rather than forcing a fixed
  three/four-file target. Merge domains only after import/surface analysis.
- **State owner:** `workflow` owns mutable workflow state and operation
  journal; `audit` only consumes snapshots. `storage` stays a lower-level
  primitive, not a separate decision-making domain.
- **Ports:** no event bus or broad service locator; compose small typed
  Git/publication/review ports in `runtime` where imports would cycle.
- **Compatibility period:** preserve old module names as thin aliases until
  all consumers and active extension points migrate; remove aliases only
  after explicitly verified compatibility and developer approval.
- **Scheduling:** R1 has no checkout changes. R2–R5 must run in order, each
  with intermediate safety evidence and exact rollback/forward-recovery
  instructions. A new SDD sub-spec plus linked detailed plan should be
  approved before production migration; do not change existing RE-05 focus
  implicitly.

## 7. Proposed acceptance criteria for the future approved spec

| ID | Verifiable criterion |
| --- | --- |
| MA-01 | Every implemented domain has a unique canonical `contract.md` and `api.py`, with documented return/errors and test owners. |
| MA-02 | `core` imports no feature package and owns no I/O/config/Git/ZIP/GitHub model. |
| MA-03 | `models.py` files contain model definitions and pure invariant checks only; loaders and external effects have separate owning files. |
| MA-04 | No forbidden domain-to-private imports or dependency cycles; static gate catches injected violations. |
| MA-05 | Relevant classes and functions have exactly one owning domain and the feature ownership map resolves to executable APIs/tests. |
| MA-06 | All public CLI modes/actions, handoff formats, state/history migrations and Git/GitHub safety semantics pass baseline and negative tests. |
| MA-07 | Magic protocol values and policy limits are owned, named, validated where configurable, and unit-tested at boundary values. |
| MA-08 | Producer and consumer flows, review retention, interrupt/restart and uncertain remote effects pass independently on synthetic repositories. |
| MA-09 | Full opt-in characterization gate, canonical/extended checks, architecture static checks and available macOS/Linux checks are recorded without false PASS claims. |
| MA-10 | No core runtime migration, new external publication or SDD state transition is performed merely by accepting a design draft. |

Acceptance means these checks have evidence on the exact source revision,
not that source moved into different directories or tests were renamed.
