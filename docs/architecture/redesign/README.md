# Modular redesign — architecture review package

**Status: PROPOSAL / NOT APPROVED.** This directory is a design-review
artifact, not a new active SDD specification and not an implementation
authorization. The existing `docs/specs/STATE.json` and accepted SDD records
remain authoritative. After developer approval, formalize the agreed scope
under the repository's SDD ownership rules before production migrations.

## Documents

- [Architecture proposal](architecture.md): target ownership, dependency DAG,
  migration principles, compatibility boundaries and acceptance criteria.
- [Source and feature ownership](feature-ownership.md): verified current symbols,
  candidate future APIs and traceability to tests/specs.
- [Linked implementation plan](implementation-plan.md): four incremental
  migration waves, source files, algorithms, recovery and evidence.
- Draft `contract.md` for each proposed domain:
  [configuration](contracts/configuration/contract.md),
  [git](contracts/git/contract.md),
  [handoff](contracts/handoff/contract.md),
  [workflow](contracts/workflow/contract.md),
  [publication](contracts/publication/contract.md),
  [review](contracts/review/contract.md),
  [audit](contracts/audit/contract.md), and
  [runtime](contracts/runtime/contract.md).

The Git read-only implementation now has a canonical
[`git/contract.md`](../../../apatch_lib/git/contract.md) in its owning
package; the design-stage Git document above is a pointer to that contract.
Other design contracts remain provisional unless the relevant domain has
a verified implementation and colocated contract. Do not interpret draft API
names as implemented Python imports.

## Evidence provenance

Inspected source: concatenated schema-v2 snapshot generated
`2026-11-11T18:15:37+00:00`, Git HEAD
`59106f9c0d7652b47fb4a84f857e1fd4361a3029`, branch
`feature/architecture-characterization-20261111`, `git_dirty=true` with nine
untracked characterization files. Its manifest has 148 tracked files, four
tracked files without content (`.DS_Store`, `.apatch/config.yaml`, `apatch`,
`apatch.conf`), and nine included untracked files. This is **not** a verified
clean `main` checkout. Existing acceptance and platform status must not be
inferred from this snapshot.

No runtime modules, persisted formats, CLI flags, tests, or existing SDD
checkpoints are changed by this review package.
