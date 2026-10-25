# Security and Recovery Boundaries

`apatch` coordinates untrusted patch archives with a developer's existing Git repository. It is **not a sandbox** and cannot validate the intent of generated source code.

## Trust boundaries

| Input | Enforcement | Remaining risk |
| --- | --- | --- |
| ZIP contents | Bounded size/count, verified digest, safe paths, regular files, duplicate and parent/child collision checks | Source changes may be malicious or logically incorrect |
| `.apatch/` | Ordinary archive files and `delete_paths` cannot change runtime state or project-owned policy; only validated metadata members are accepted | A developer can intentionally edit policy outside the ZIP workflow |
| Project checks | Explicit argv from tracked `.apatch/config.yaml`; no implicit shell; bounded execution (`check_timeout_seconds`, default 900) | Check commands and scripts they invoke run with the developer's normal OS permissions |
| Git and GitHub | Live branch/commit/PR checks, fast-forward restrictions, review/CI policy, bounded GitHub reads | A remote mutation can succeed despite a lost response; reconcile before retry |
| Cached state | Atomic writes, stable advisory locks, restricted file paths | Checkpoints are records, not independent evidence that remote actions completed |

## Applying and recovering safely

1. Inspect the ZIP and its embedded handoff before using unattended operations. Avoid automatic PR merge for archives that have not undergone code review.
2. The extractor validates all target paths and prepares file contents before replacing destination files. This reduces predictable partial writes but **does not make a multi-file patch atomic across a crash or disk failure**.
3. On an interrupted `APL`, inspect `git status`, `.apatch/apply_patch.state.json`, the applied-patch journal, and `.apatch/backups/` if overlap backups were created. Do not blindly repeat extraction or delete the recorded state.
4. `skipApproves=true` only disables interactive confirmation. It does not bypass Git, ZIP, branch, or GitHub safety checks. In LOOSE mode, it can also auto-approve an explicitly warned post-check manual change, so unattended publication deserves extra scrutiny.
5. `STS` is read-only and uses local evidence; GitHub outcomes marked `UNKNOWN_REMOTE_RESULT` require a separate live check.

Runtime locking uses POSIX `fcntl` and is targeted at Linux and macOS. Native Windows is not a supported/tested target. CI verifies behavior on both Linux and macOS; actual GitHub integration is covered by mocks, not live publication tests.

The project currently has no published license. Maintainers must select a license explicitly; its terms cannot be inferred from repository visibility.
