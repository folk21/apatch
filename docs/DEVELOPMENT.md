# Development and Testing

This guide covers local development, tests, and documentation ownership. See [Architecture](ARCHITECTURE.md) for module boundaries and [Usage](USAGE.md) for public CLI behavior.

## Running the apatch tests

Run the tests from the `apatch` directory after installing the dependencies:

```bash
cd /path/to/apatch
sh ./run_tests.sh
```

The script uses `.venv/bin/python` when available and otherwise falls back to `python3`. It checks that PyYAML is installed in the selected interpreter before running the suite. If PyYAML is missing, install the dependencies with `.venv/bin/python -m pip install -r requirements.txt`; activating a virtual environment alone does not install its dependencies.

To run the tests directly with the project virtual environment:

```bash
.venv/bin/python -B -m unittest discover -s tests -v
```

`-B` prevents Python bytecode cache files, and `-v` prints each test result. The suite uses temporary local Git repositories; its GitHub interactions are mocked. No changes are made to your actual project repositories. Python, PyYAML, and Git are required; GitHub CLI access is not required to run the tests. The tests also support case-insensitive filesystems, including typical macOS installations.

## Local verification

- Run focused regression tests for affected modes and edge cases before the full suite.
- Use temporary repositories and local bare remotes for Git integration tests; keep GitHub interactions mocked.
- For shell changes, run `sh -n apatch.sh` and `sh -n run_tests.sh`.
- For documentation changes, verify relative links, file paths, CLI examples, and the separation between global and project configuration.
- Report the tests actually run and their environment. Passing Linux tests does not establish macOS compatibility.

## SDD documentation lifecycle

The [specification index](specs/README.md) is a placeholder for the next SDD stage. **No normative product specification is introduced by this documentation reorganization.**

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
| `docs/specs/README.md` | Specification index and lifecycle (no active spec yet) |

Write changes in the owning document and cross-link it. Avoid duplicating README sections across multiple files.
