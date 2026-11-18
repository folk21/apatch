# Handoff domain contract (R2.2 metadata, R3.3 archives, R3.4 producer, R3.5 ledger, R3.6 cache)

## Ownership and published API

`handoff` owns immutable `Handoff`/`Archive` values, schema-v1 decoding,
repository-relative path validation, ZIP inspection, and ZIP source extraction.
`handoff.models` does not perform I/O. `handoff.inspection` reads archive bytes
and source-path/Git tracking evidence; `handoff.extraction` writes source bytes
only after identity revalidation. `handoff.service` implements the public
`ArchiveOperations` protocol defined in `handoff.api`. The
`handoff.producer` package owns source discovery, canonical preflight, and
verified ZIP creation. Its `models.py` contains immutable results; only
`preflight.py` and `packaging.py` perform I/O.

`ArchiveOperations` describes the *actual* boundary consumed by
`BranchPatchActions`:

- `inspect(config, handoff, root, *, before_apply=True) -> Archive`: read and
  validate the selected archive, returning its SHA-256, changed paths, and
  optional reserved metadata; no source writes or workflow-state mutations.
- `apply(config, handoff, root, archive) -> None`: revalidate source ZIP bytes
  and filesystem paths before staging replacements and requested deletions.
  The workflow owns approval, backup admission, state, and history journaling.
- `handoff_from_zip(config, root, name) -> Handoff`: validate embedded metadata
  and associate the selected archive's verified digest with the handoff.

`ZipArchiveOperations` is the default implementation. Consumers may inject a
conforming archive port for isolated testing or alternate implementations,
without introducing backend selection through untrusted handoff metadata.
Runtime `isinstance` on this protocol checks only method presence, not
signature or safety correctness. Normal static typing verifies signatures.

`ProducerOperations` is a second structural protocol published from `handoff.api`
and used by `apatch_preflight.py` and `apatch_pack.py`:

- `discover(project) -> SourceCandidates`: read-only candidate inspection,
  including tracked deletions and untracked files, without authorizing edits.
- `preflight(project, installation, *, prepare=False) -> PreflightResult`:
  check Git branch/HEAD, whitespace, configured canonical checks, source and
  index stability; only `prepare=True` runs explicitly configured formatters.
- `pack(project, installation, destination, *, branch, message, included,
  deleted=(), prepare=False, base_commit=None) -> PackagingResult`:
  validate the manifest, re-verify Git/bytes before exclusive ZIP publication,
  and embed schema-v1 metadata with no self-referential digest.

`VerifiedSourceProducer` is the default implementation. It never creates
branches, commits, PRs, or modifies target Git state. The previous
`artifact_preflight.py` and `artifact_packaging.py` imports still work;
packaging's historical `preflight` and `_read_source_file` monkeypatch seams
are preserved through explicit callable injection. New consumers should use
the port, not depend on producer implementation files or legacy shims.

The module also exports `load_handoff`, `parse_handoff_payload`, `safe_relative`,
metadata constants, `Archive`, and the historical free functions. The legacy
`apatch_lib.patch` module retains identity-preserving aliases; do not make new
internal dependencies on it.

## Safety and error invariants

- Embedded metadata rejects `patch_sha256`; legacy JSON may carry a verified
  SHA-256. A selected ZIP must match its basename and repository identity.
- Reject unsupported metadata versions/fields, nonregular members, duplicate
  paths or metadata, traversal/absolute paths, symlinked or otherwise unsafe
  parents and destinations, oversized/corrupted archives, protected runtime
  paths, and untracked explicit deletion targets.
- Bound member count, compressed and uncompressed size; read only declared
  source files. A fresh inspection before writes must agree with the original
  archive digest and source scope.
- Extraction stages regular files under their intended parents, fsyncs staged
  bytes and replaces destination files. Explicit tracked deletions follow
  replacements, retaining the existing non-transactional filesystem semantics.
- The archive service does not set workflow phases, persist applied history,
  override dirty-worktree checks, or authorize publishing. An interrupted
  application remains governed by the existing `applying` checkpoint/recovery.
- Preserve existing `Abort` categories and compatibility import identities.
  No additional Git/GitHub mutation is authorized by this move.

## Patch-ledger port and persistent ownership (R3.5)

`handoff/history/` owns the two related, independently locked persistence
formats: an optional append-only created-patch registry and the existing
applied-patch journal. The immutable `HistoryEntry` is defined in
`history/models.py`; `history/journal.py` and `history/registry.py` retain the
original parser, no-follow checks, byte bounds, stable lock files, fsync and
atomic replacement algorithms. `PatchLedgerOperations` is defined in
`history/api.py` and exposed from `handoff.api`; its default implementation is
`ProjectPatchLedger` in `history/service.py`.

- `locked(path) -> AbstractContextManager[AppliedHistory]` provides a live
  history object exclusively within the lock context. Consumers must not
  retain it beyond the context or bypass locking for mutations.
- `assert_order(root, patch_name, history, incoming=None) -> bool` rejects
  missing predecessors and conflicting registry prefixes before applying
  source bytes. Absence of both registries remains compatible.
- `persist_registry(root, incoming) -> bool` accepts only an append-only
  extension and atomically writes a valid registry under its own stable lock.

`AppliedHistory` is a structural protocol for the journal methods and path
used by those operations. `BranchPatchActions` depends on the injected ledger
port and archive port; the default ledger uses the same existing functions and
preserves the historical `branch_patch` monkeypatch locations. Existing
`created_patches.py` and `patch_history.py` remain identity-preserving import
adapters for external callers; `loose`/`force` keep their local monkeypatch
seams until their workflow-level adapters are migrated.

There are no migrations of on-disk records, locks or checkpoints. Ledger
parsing and ordering are not ZIP content verification or proof of a Git commit.

## Remaining modularization

## Verified handoff cache port (R3.6)

`handoff/cache/api.py` defines the `HandoffCacheOperations` structural protocol:
`load(root) -> Handoff` is read-only, `preflight_write(root) -> None`
validates the cache and recovery targets before extraction, and
`save(root, handoff) -> None` atomically caches only a verified ZIP identity.
`handoff/cache/service.py` contains the original persistence and recovery
algorithms and the default `ProjectHandoffCache` implementation. The runtime
dispatcher consumes the injected port; handoff selection supports injecting
the same port while retaining its legacy lookup patch seam.

The stable `params.json.lock`, bounded UTF-8 payload, symlink checks,
mode-0600 atomic replacement, fsync and hard-linked invalid-cache backups
are unchanged. Cached data is not applied-history or workflow evidence.
`apatch_lib.params_cache` remains an import-compatible alias module. There
is no schema or cache migration.

`zip_resume.py` continues to own resume verification until R3.7.

## Verification

Test the boundary with `tests.test_handoff_archive_boundaries` plus the
existing handoff, safety, ZIP resume/recovery, and producer test suites.
Also run `tests.test_artifact_preflight`, `tests.test_artifact_packaging`,
and `tests.test_handoff_producer_boundaries`, plus
`tests.test_handoff_history_boundaries` and history recovery regressions. Producer fault-injection tests
must keep failed source verification from writing a final ZIP; CLI JSON output
must remain a single machine-readable value. Use disposable Git repositories;
do not infer Linux success proves macOS
filesystem and path behavior.
