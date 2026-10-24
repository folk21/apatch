"""Supervised incremental patch workflow with deferred Git publishing."""

import logging
import os
import shutil
import tempfile
from pathlib import Path

from .branch_guard import assert_no_unfinished_feature_branches
from .gitutil import (branch_exists, confirm, current_branch, head, output,
                      remote_head, run, status_paths, worktree_fingerprint)
from .model import Abort
from .patch import apply, inspect
from .patch_history import locked_history
from .state import save


LOGGER = logging.getLogger("apatch.loose")
PENDING_PHASES = {"applying", "patch_applied", "verified"}


class LooseActions:
    """Relax workflow bookkeeping without relaxing Git and filesystem safety."""

    def __init__(self, workflow):
        self.w = workflow

    def branch(self):
        branch = current_branch(self.w.root)
        if not branch:
            raise Abort("LOOSE requires a checked-out named branch")
        return branch

    def prepare_branch(self, with_patch=False):
        w = self.w
        target = w.handoff.branch
        current = self.branch()
        origin = "REUSED"
        if current == target:
            print(f"LOOSE: already on {target}; using the existing branch.")
        elif branch_exists(w.root, target):
            if not confirm(f"LOOSE: Switch from {current} to existing branch {target}?"):
                return
            run(["git", "switch", target], w.root)
        else:
            existing_remote = remote_head(w.root, w.config, target)
            if existing_remote:
                if not confirm(f"LOOSE: Track existing remote branch {target}?"):
                    return
                run(["git", "fetch", "--no-tags", w.config.remote,
                     f"refs/heads/{target}:refs/remotes/{w.config.remote}/{target}"], w.root)
                run(["git", "switch", "--track", "-c", target,
                     f"{w.config.remote}/{target}"], w.root)
            else:
                if not confirm(f"LOOSE: Create {target} from {current}, keeping working-tree changes?"):
                    return
                assert_no_unfinished_feature_branches(w.root, w.config, target)
                run(["git", "switch", "-c", target], w.root)
                origin = "CREATED"
        if w.phase in {"new", "branch_created"}:
            w.record.update(phase="branch_created", branch_base=head(w.root),
                            applied_branch=target, branch_origin=w.record.get("branch_origin", origin),
                            remote_url=output(["git", "remote", "get-url", w.config.remote], w.root))
            w.persist()
        if with_patch:
            self.apply_patch()

    def _backup_overlaps(self, overlap):
        """Retain user-edited file contents before an explicitly approved overwrite."""
        w = self.w
        sources = [path for path in sorted(overlap) if (w.root / path).is_file()]
        if not sources:
            return None
        backup_root = w.root / ".apatch" / "backups"
        if backup_root.is_symlink() or (backup_root.exists() and not backup_root.is_dir()):
            raise Abort("Unsafe backup directory in .apatch/backups")
        backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = Path(tempfile.mkdtemp(prefix="overlap-", dir=backup_root))
        try:
            for relative in sources:
                source = w.root / relative
                destination = directory / relative
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(source, destination, follow_symlinks=False)
                os.chmod(destination, 0o600)
        except OSError as exc:
            raise Abort(f"Could not preserve overlapping edits; backup retained at {directory}: {exc}") from exc
        print(f"Backed up {len(sources)} overlapping file(s) to {directory}")
        LOGGER.warning("LOOSE overlapping edits backed up path=%s count=%d", directory, len(sources))
        return str(directory)

    def apply_patch(self):
        w = self.w
        branch = self.branch()
        archive = inspect(w.config, w.handoff, w.root)
        before = status_paths(w.root)
        overlap = set(before) & (set(archive.changed) | set(w.handoff.delete_paths))
        if w.handoff.base_commit and head(w.root) != w.handoff.base_commit:
            print("WARNING: Current HEAD differs from the handoff base_commit. "
                  "This may be intentional for a subsequent patch.")
        if branch != w.handoff.branch:
            print(f"WARNING: Applying on {branch}, not the planned branch {w.handoff.branch}.")
        if before:
            print(f"LOOSE: {len(before)} pre-existing changed path(s) will remain in the worktree.")
        if overlap:
            print("WARNING: The ZIP will overwrite or delete these locally changed paths:")
            for path in sorted(overlap):
                print(f"  {before[path]} {path}")
            if not confirm("Back up these paths and permit their replacement by the ZIP?"):
                return
        with locked_history(w.config.applied_patches_path) as history:
            if not w.branch_patch.warn_if_previously_applied(history):
                return
            if not confirm(f"LOOSE: Apply {w.handoff.patch} on {branch} without discarding other edits?"):
                return
            latest_overlap = set(status_paths(w.root)) & (
                set(archive.changed) | set(w.handoff.delete_paths))
            if latest_overlap != overlap:
                raise Abort("Overlapping changed paths changed during confirmation; review and retry")
            backup = self._backup_overlaps(overlap)
            w.record.update(
                phase="applying", applied_branch=branch,
                before_patch_head=head(w.root), archive_sha256=archive.sha256,
                remote_url=output(["git", "remote", "get-url", w.config.remote], w.root),
                loose_backup=backup,
            )
            w.record.setdefault("branch_origin", "REUSED")
            for field in ("verified_fingerprint", "verified_head", "verified_branch",
                          "commit_sha", "pushed_sha"):
                w.record.pop(field, None)
            w.persist()
            apply(w.config, w.handoff, w.root, archive)
            _, paths = worktree_fingerprint(w.root)
            w.record.update(phase="patch_applied", changed_paths=sorted(paths))
            history.append(w.handoff.patch, w.handoff.branch, branch)
            w.persist()
        print("Patch applied. Keep editing, apply another ZIP, run checks, or commit when ready.")

    def verify(self):
        w = self.w
        branch = self.branch()
        if not w.config.checks:
            raise Abort("No project verification commands configured")
        before, paths = worktree_fingerprint(w.root)
        for argument in (["git", "diff", "--check"],
                         ["git", "diff", "--cached", "--check"]):
            result = run(argument, w.root, check=False)
            if result.returncode:
                print("WARNING: Git whitespace check reported problems; "
                      "the project verification commands will still run.")
                print((result.stdout + result.stderr).strip())
        for command in w.config.checks:
            run(list(command), w.root, stream_output=True)
        after, _ = worktree_fingerprint(w.root)
        if head(w.root) != (w.record.get("before_patch_head") or head(w.root)):
            print("WARNING: HEAD has changed since patch application.")
        if before != after:
            print("WARNING: Checks modified the worktree. Re-run checks after reviewing the edits.")
            w.record["phase"] = "patch_applied"
            w.persist()
            return
        if paths:
            w.record.update(phase="verified", verified_fingerprint=after,
                            verified_head=head(w.root), verified_branch=branch)
        else:
            w.record["verified_commit"] = head(w.root)
        w.persist()
        print("Canonical checks passed for the current worktree snapshot.")

    def _pending(self, branch):
        w = self.w
        return [(key, record) for key, record in w.state["workflows"].items()
                if isinstance(record, dict)
                and record.get("repository") == str(w.root.resolve())
                and record.get("phase") in PENDING_PHASES
                and (record.get("applied_branch") == branch or key == w.key)]

    def commit(self):
        w = self.w
        branch = self.branch()
        fingerprint, paths = worktree_fingerprint(w.root)
        if not paths:
            print("No staged or working-tree changes to commit.")
            return
        pending = self._pending(branch)
        print(f"LOOSE: Commit {len(paths)} changed path(s) on {branch}:")
        for path, code in sorted(paths.items()):
            print(f"  {code} {path}")
        if pending:
            print("Associated pending patches:")
            for _, record in pending:
                print(f"  {record.get('patch_file')}")
                if record.get("phase") == "applying":
                    print("  WARNING: This patch extraction was interrupted; review its files before committing.")
        if branch != w.handoff.branch:
            print(f"WARNING: Committing on {branch}, not the planned branch {w.handoff.branch}.")
        if branch == w.config.base:
            print(f"WARNING: This commit will be created directly on the base branch {branch}.")
        if (w.record.get("verified_fingerprint") != fingerprint
                or w.record.get("verified_head") != head(w.root)
                or w.record.get("verified_branch") != branch):
            print("WARNING: These exact changes have not passed canonical checks. "
                  "Manual edits or additional patches may have changed them.")
        print("Commit message:\n" + w.handoff.message)
        if not confirm(f"Stage ALL listed paths and commit on {branch} without pushing?"):
            return
        run(["git", "add", "-A"], w.root)
        staged_summary = run(["git", "diff", "--cached", "--stat"], w.root).stdout
        print(staged_summary, end="" if staged_summary.endswith("\n") else "\n")
        staged = run(["git", "diff", "--cached", "--name-only", "-z"], w.root).stdout
        if not staged:
            print("Nothing staged; no commit created.")
            return
        whitespace = run(["git", "diff", "--cached", "--check"], w.root, check=False)
        if whitespace.returncode:
            print("WARNING: Staged changes contain Git whitespace warnings:")
            print((whitespace.stdout + whitespace.stderr).strip())
        if not confirm("Create this reviewed commit, including manually edited files?"):
            return
        run(["git", "commit", "-F", "-"], w.root, input_text=w.handoff.message,
            log_commit_message=w.handoff.message)
        committed_sha = head(w.root)
        # Update only pending patch records associated with this checked-out branch.
        for _, record in pending:
            record.update(phase="committed", commit_sha=committed_sha,
                          applied_branch=branch, combined_commit=True)
        if w.key not in {key for key, _ in pending}:
            w.record.update(phase="committed", commit_sha=committed_sha,
                            applied_branch=branch, manual_commit_without_patch=True)
            w.record.setdefault("branch_origin", "REUSED")
        w.persist()
        with locked_history(w.config.applied_patches_path) as history:
            for _, record in pending:
                history.record_commit_branch(record["patch_file"], record["branch"], branch)
        print(f"Committed {committed_sha} on {branch}. Push remains a separate action.")

    def push(self):
        w = self.w
        branch = self.branch()
        current_sha = head(w.root)
        if status_paths(w.root):
            print("WARNING: Uncommitted work remains. Only committed Git history will be pushed.")
        if branch != w.handoff.branch:
            print(f"WARNING: Pushing {branch}, not the planned branch {w.handoff.branch}.")
        if branch == w.config.base:
            print(f"WARNING: {branch} is the configured base branch; pushing it directly.")
        remote_url = output(["git", "remote", "get-url", w.config.remote], w.root)
        previous_url = w.record.get("remote_url")
        if previous_url and previous_url != remote_url:
            print(f"WARNING: Remote URL changed from {previous_url} to {remote_url}.")
            if not confirm("Continue using the changed Git remote URL?"):
                return
        print(f"Push destination: {w.config.remote} ({remote_url})")
        remote = remote_head(w.root, w.config, branch)
        if remote and remote != current_sha:
            run(["git", "fetch", "--no-tags", w.config.remote, f"refs/heads/{branch}"], w.root)
            ancestor = run(["git", "merge-base", "--is-ancestor", remote, current_sha],
                           w.root, check=False)
            if ancestor.returncode != 0:
                raise Abort("Remote branch is not an ancestor; LOOSE never force-pushes history")
        if remote != current_sha:
            if not confirm(f"Push committed HEAD {current_sha} to {w.config.remote}/{branch}?"):
                return
            run(["git", "push", "-u", w.config.remote, f"HEAD:refs/heads/{branch}"], w.root)
            if remote_head(w.root, w.config, branch) != current_sha:
                raise Abort("Remote HEAD differs after push; inspect remote history")
        else:
            print(f"Remote {w.config.remote}/{branch} already matches committed HEAD.")
        updated = 0
        reconciled = []
        for record in w.state["workflows"].values():
            if not isinstance(record, dict) or record.get("repository") != str(w.root.resolve()):
                continue
            if record.get("phase") != "committed" or record.get("applied_branch") != branch:
                continue
            committed_sha = record.get("commit_sha")
            if not committed_sha:
                continue
            if run(["git", "merge-base", "--is-ancestor", committed_sha, current_sha],
                   w.root, check=False).returncode == 0:
                record.update(phase="pushed", pushed_sha=current_sha)
                if not record.get("manual_commit_without_patch"):
                    reconciled.append((record["patch_file"], record["branch"]))
                updated += 1
        if reconciled:
            with locked_history(w.config.applied_patches_path) as history:
                for patch_name, planned_branch in reconciled:
                    history.record_commit_branch(patch_name, planned_branch, branch)
        if updated:
            save(w.config.state_path, w.state)
        print(f"Push reconciled on {branch}; {updated} workflow checkpoint(s) updated.")

    def pr(self):
        self.w.force_actions.pr()

    def merge(self):
        self.w.force_actions.merge()

    def sync(self):
        self.w.force_actions.sync()
