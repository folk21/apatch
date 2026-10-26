# Development and Testing

This guide covers local development, tests, and documentation ownership. See [Architecture](ARCHITECTURE.md) for module boundaries and [Usage](USAGE.md) for public CLI behavior.

## Running the apatch tests

Run the tests from the `apatch` directory after installing the dependencies:

```bash
cd /path/to/apatch
sh ./run_tests.sh
sh ./run_rare_checks.sh
```

The script uses `.venv/bin/python` when available and otherwise falls back to `python3`. It checks that PyYAML is installed in the selected interpreter before running the suite. If PyYAML is missing, install the dependencies with `.venv/bin/python -m pip install -r requirements.txt`; activating a virtual environment alone does not install its dependencies.

To run the tests directly with the project virtual environment:

```bash
.venv/bin/python -B -m unittest discover -s tests -v
```

`run_tests.sh` defaults to a focused **regular** suite covering ZIP application, branch transitions, Git safety, GitHub guards, progress persistence, and launcher contracts. `quick` and `regular` are aliases for that suite. This is also the default local `CHK` command when a target repository config selects `./run_tests.sh`.

`run_rare_checks.sh` runs **all** tests, including the regular suite, to preserve complete regression coverage with no omitted or duplicated test-selection lists. `run_tests.sh full` remains an equivalent compatibility command. Run the regular suite after each implementation increment and the extended suite locally before handoff, release, or merge. GitHub Actions has a manual `workflow_dispatch` trigger only; it does **not** run on push or pull request. The optional manual workflow still runs the extended suite across the configured Python/macOS/Linux matrix. A successful local `CHK` does not imply that extended tests have run. Verify that GitHub branch protection/rulesets do not require automatic checks before disabling them.

Test durations depend heavily on the platform: the extended suite runs many subprocess-based temporary-Git integration tests and can take substantially longer on macOS. The regular suite avoids most of those invocations. Tests are grouped in `tests/test_handoffs.py`, `test_safety.py`, `test_sequences.py`, `test_history.py`, `test_branches.py`, `test_modes.py`, `test_status.py`, `test_config_cli.py`, `test_github.py`, `test_progress.py`, `test_operation_journal.py`, `test_validation.py`, and `test_runner_scripts.py`. Shared fixtures live in `tests/_support.py`.

`-B` prevents bytecode cache files. Tests use temporary Git repositories and mocked GitHub commands. No developer project repository is modified. Python, PyYAML, and Git are required; the GitHub CLI is not required for tests. Linux results alone do not guarantee macOS behavior.

Global progress tests live in `tests/test_progress.py`; they use temporary tool installations and project roots, verify cross-process locking, collision-safe histories, symlink protection, idempotent replay, redaction, sequence events, CLI isolation, read-only overview, configuration limits, and malformed index handling.

Project-local run tests live in `tests/test_operation_journal.py`; they cover schema-v1 migration, journal validation, separate process writers, STARTED/retry semantics, action outcomes, `opSeq` correlation, and read-only status. Preserve the distinction between per-target operation evidence and installed-tool progress summaries when changing either format.

`test_audit.py` covers the read-only `11 [AUD]` command, missing and reordered
patches, duplicate names, historical v1 records, unresolved runs, local Git
conflicts, optional mocked GitHub evidence, dirty worktrees, and immutable
state/history/refs. It never contacts a live GitHub API.

`test_handoffs.py` also covers explicit cross-invocation `followup=true`. Rejected
follow-ups preserve prior workflow checkpoints while recording the failed attempt;
accepted repairs keep both ZIP histories and one combined commit. Redaction
assertions must match sensitive tokens or diagnostic fields, not platform path
components such as macOS `/private/var`.

## Local verification

- Run focused regression tests for affected modes and edge cases before the extended suite. Keep high-priority scenarios in the curated regular command when new regressions justify it.
- Use temporary repositories and local bare remotes for Git integration tests; keep GitHub interactions mocked.
- For shell changes, run `sh -n apatch.sh`, `sh -n run_tests.sh`, and `sh -n run_rare_checks.sh`.
- For documentation changes, verify relative links, file paths, CLI examples, and the separation between global and project configuration.
- Report the tests actually run and their environment. Passing Linux tests does not establish macOS compatibility.

## SDD documentation lifecycle

The [specification index](specs/README.md) is the authoritative list of active **DRAFT** specifications, advisory plans, independently prepared implementation candidates, and verified delivery status. Implemented slices are not automatically accepted normative requirements.

When the developer explicitly requests specification work, add one owning active spec with scope, invariants, acceptance criteria, and verifiable increments. Keep implementation plans advisory and separate from normative requirements. Use an existing convention before introducing new files. Do not infer completion or invent future stage IDs.

## Documentation ownership

| File | Primary concern |
| --- | --- |
| `README.md` | Project overview and navigation |
| `AGENTS.md` | Repository-level, actionable contributor and agent rules |
| `docs/INSTALLATION.md` | Prerequisites, installation, initial repository setup |
| `docs/USAGE.md` | User-facing CLI reference, configuration, safety, and recovery |
| `docs/ARCHITECTURE.md` | Component boundaries and runtime design |
| `docs/DEVELOPMENT.md` | Tests, development workflow, and documentation ownership |
| `docs/specs/README.md` | Draft specification index, implementation status, and lifecycle |

Write changes in the owning document and cross-link it. Avoid duplicating README sections across multiple files.
