"""Supervised incremental patch workflow with deferred Git publishing."""

import logging
import os
import shutil
import tempfile
from pathlib import Path

from .core.enums import WorkflowPhase
from .core.contracts import ActionResult
from .branch_guard import assert_no_unfinished_feature_branches
from .created_patches import persist_registry
from .commit_scope import (NeedsVerification, WaitingForUser, assert_scope_unchanged,
                           changed_contents_fingerprint, inspect_commit_scope,
                           policy_fingerprint)
from .console import check_result_label
from .gitutil import (branch_exists, confirm, current_branch, head, output,
                      remote_head, run, status_paths, worktree_fingerprint,
                      worktree_inventory, worktree_change_details)
from .model import Abort, CheckWorktreeChanged
from .patch import apply, inspect
from .patch_history import locked_history
from .session_continuation import require_session_continuation
from .session import record_session_commit
from .state import save


LOGGER = logging.getLogger("apatch.loose")
PENDING_PHASES = {WorkflowPhase.APPLYING, WorkflowPhase.PATCH_APPLIED, WorkflowPhase.VERIFIED}


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
        if with_patch:
            w.branch_patch.assert_patch_order()
        w.branch_patch.assert_history_well_formed()
        target = w.handoff.branch
        current = self.branch()
        already_prepared = current == target and w.phase == WorkflowPhase.BRANCH_CREATED
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
                     f"refs/heads/{target}:refs/remotes/{w.config.remote}/{target}"],
                    w.root, timeout=w.config.github_timeout_seconds)
                run(["git", "switch", "--track", "-c", target,
                     f"{w.config.remote}/{target}"], w.root)
            else:
                if not confirm(f"LOOSE: Create {target} from {current}, keeping working-tree changes?"):
                    return
                assert_no_unfinished_feature_branches(w.root, w.config, target)
                run(["git", "switch", "-c", target], w.root)
                origin = "CREATED"
        if w.phase in {WorkflowPhase.NEW, WorkflowPhase.BRANCH_CREATED}:
            w.record.update(phase=WorkflowPhase.BRANCH_CREATED.value, branch_base=head(w.root),
                            applied_branch=target, branch_origin=w.record.get("branch_origin", origin),
                            remote_url=output(["git", "remote", "get-url", w.config.remote], w.root))
            w.persist()
        if with_patch:
            return self.apply_patch()
        if already_prepared:
            return ActionResult.already_satisfied("Existing feature branch was reverified")
        return True

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

    def assert_followup_selection(self, *, archive=None):
        """Require explicit intent and a matching uncommitted predecessor on the feature branch."""
        w = self.w
        if w.phase != WorkflowPhase.NEW or not (w.zip_selected or
                (archive is not None and archive.embedded_handoff is not None)):
            return
        branch = self.branch()
        if branch == w.config.base:
            if w.allow_followup_zip:
                raise Abort("followup=true requires the existing feature branch, not the base branch")
            return
        if not w.allow_followup_zip:
            raise Abort("A new self-contained ZIP on an unfinished feature branch requires "
                        "followup=true or an upfront handoffSeq")
        if branch != w.handoff.branch:
            raise Abort(f"Follow-up ZIP targets {w.handoff.branch}, but current branch is {branch}")
        if not status_paths(w.root):
            raise Abort("followup=true requires previous uncommitted changes on the feature branch")
        current_head = head(w.root)
        current_remote_url = output(["git", "remote", "get-url", w.config.remote], w.root)
        matching = any(
            isinstance(record, dict)
            and record.get("repository") == str(w.root.resolve())
            and record.get("branch") == w.handoff.branch
            and record.get("applied_branch") == branch
            and record.get("phase") in PENDING_PHASES - {WorkflowPhase.APPLYING}
            and record.get("before_patch_head") == current_head
            and record.get("remote_url") == current_remote_url
            for key, record in w.state["workflows"].items() if key != w.key
        )
        if not matching:
            raise Abort("followup=true requires a matching unfinished, uncommitted ZIP workflow "
                        "at the current HEAD; inspect 10 [STS] before retrying")

    def assert_session_continuation(self, *, archive=None):
        """Recheck the narrowly scoped internal FS-03 admission before APL."""
        session_id = self.w._session_continuation_id
        if session_id is None:
            raise Abort("Session-aware APL requires an explicit active session")
        return require_session_continuation(self.w.root, self.w.config, self.w.handoff,
                                            session_id, archive=archive)

    def apply_patch(self):
        w = self.w
        branch = self.branch()
        archive = inspect(w.config, w.handoff, w.root)
        before = status_paths(w.root)
        zip_first = archive.embedded_handoff is not None and branch == w.config.base
        session_id = getattr(w, "_session_continuation_id", None)
        if session_id is None:
            self.assert_followup_selection(archive=archive)
        else:
            self.assert_session_continuation(archive=archive)
        if zip_first and before:
            raise Abort("A new self-contained ZIP must start on a clean base branch")
        if zip_first:
            w.assert_base()
            if remote_head(w.root, w.config, w.config.base) != head(w.root):
                raise Abort("Base branch differs from remote; cannot start an apply-first ZIP workflow")
        overlap = set(before) & (set(archive.changed) | set(w.handoff.delete_paths))
        if overlap and getattr(w, "_goal_guarded_continuation", False):
            raise WaitingForUser(
                "WAITING_FOR_USER: The selected ZIP overlaps changed paths: "
                + ", ".join(sorted(overlap)[:8])
                + "; this goal cannot authorize replacing developer edits")
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
            w.branch_patch.assert_patch_order(history, archive)
            if not w.branch_patch.warn_if_previously_applied(history):
                return
            if not confirm(f"LOOSE: Apply {w.handoff.patch} on {branch} without discarding other edits?"):
                return
            latest_overlap = set(status_paths(w.root)) & (
                set(archive.changed) | set(w.handoff.delete_paths))
            if latest_overlap != overlap:
                raise Abort("Overlapping changed paths changed during confirmation; review and retry")
            if session_id is not None:
                self.assert_session_continuation(archive=archive)
            backup = self._backup_overlaps(overlap)
            w.record.update(
                phase="applying", applied_branch=branch,
                before_patch_head=head(w.root), archive_sha256=archive.sha256,
                remote_url=output(["git", "remote", "get-url", w.config.remote], w.root),
                loose_backup=backup,
                zip_first=zip_first,
            )
            w.record.setdefault("branch_origin", "REUSED")
            for field in ("verified_fingerprint", "verified_head", "verified_branch",
                          "guarded_verification", "commit_sha", "pushed_sha"):
                w.record.pop(field, None)
            w.record["patch_footprint"] = sorted(
                set(archive.changed) | set(w.handoff.delete_paths))
            w.record["preexisting_staged_paths"] = sorted(
                path for path, code in before.items() if code[0] not in {" ", "?"})
            w.persist()
            apply(w.config, w.handoff, w.root, archive)
            _, paths = worktree_fingerprint(w.root)
            w.record.update(phase=WorkflowPhase.PATCH_APPLIED.value, changed_paths=sorted(paths))
            persist_registry(w.root, archive.created_registry)
            history.append(w.handoff.patch, w.handoff.branch, branch)
            w.persist()
        print("Patch applied. Keep editing, apply another ZIP, run checks, or commit when ready.")
        return True

    def _invalidate_verification(self):
        w = self.w
        for field in ("verified_fingerprint", "verified_head", "verified_branch",
                      "verified_commit", "guarded_verification", "code_review"):
            w.record.pop(field, None)
        if w.record.get("phase") == WorkflowPhase.VERIFIED.value:
            w.record["phase"] = WorkflowPhase.PATCH_APPLIED.value
        w.persist()

    @staticmethod
    def _report_check_changes(before, after, *, phase):
        details = worktree_change_details(before, after)
        print(check_result_label(f"==> {phase}: repository paths changed; "
                                 "all edits were preserved. A concurrent editor "
                                 "may have contributed.", stable=False))
        for name, differences in details[:24]:
            print(f"    {name!r}: {', '.join(differences)}")
        if len(details) > 24:
            print(f"    ... and {len(details) - 24} more changed paths")
        return details

    @staticmethod
    def _symlink_identity_changed(before, after):
        for name in before.keys() & after.keys():
            old, new = before[name], after[name]
            if (old.symlink_target != new.symlink_target
                    or (old.kind != new.kind and "symlink" in {old.kind, new.kind})):
                return True
        return False

    def _prepare_macro_checks(self):
        """Run opt-in preparation before guarded staging, never in direct CHK."""
        w = self.w
        if not w.config.prepare_checks:
            return
        self._invalidate_verification()
        before = worktree_inventory(w.root)
        initial_policy = policy_fingerprint(w.root, w.config)
        try:
            for index, command in enumerate(w.config.prepare_checks, start=1):
                print(f"==> PREPARE {index}/{len(w.config.prepare_checks)}", flush=True)
                run(list(command), w.root, stream_output=True,
                    timeout=w.config.check_timeout_seconds,
                    idle_timeout=w.config.check_idle_timeout_seconds)
        finally:
            after = worktree_inventory(w.root)
            if before != after:
                self._report_check_changes(before, after, phase="PREPARE")
        if self._symlink_identity_changed(before, after):
            raise NeedsVerification("NEEDS_VERIFICATION: Symlink identity changed during "
                                    "preparation; review it before staging")
        if policy_fingerprint(w.root, w.config) != initial_policy:
            raise Abort("CHECK_POLICY_DRIFT: Project configuration changed during preparation")

    def verify(self, *, macro_policy=False, before_retry=None):
        w = self.w
        branch = self.branch()
        if not w.config.checks:
            raise Abort("No project verification commands configured")
        policy = w.config.check_worktree_policy if macro_policy else "stop"
        self._invalidate_verification()
        for attempt in range(1, 3 if policy == "recheck_once" else 2):
            before, _ = worktree_fingerprint(w.root)
            before_paths = worktree_inventory(w.root)
            starting_head = head(w.root)
            print(f"==> CANONICAL CHECK PASS {attempt}/"
                  f"{2 if policy == 'recheck_once' else 1}", flush=True)
            failure = None
            whitespace_warnings = []
            try:
                for argument in (["git", "diff", "--check"],
                                 ["git", "diff", "--cached", "--check"]):
                    result = run(argument, w.root, check=False)
                    if result.returncode:
                        print("WARNING: Git whitespace check reported problems; "
                              "the project verification commands will still run.")
                        print((result.stdout + result.stderr).strip())
                        whitespace_warnings.extend(
                            line.strip()[:240]
                            for line in (result.stdout + result.stderr).splitlines()[:3]
                            if line.strip())
                for command in w.config.checks:
                    run(list(command), w.root, stream_output=True,
                        timeout=w.config.check_timeout_seconds,
                        idle_timeout=w.config.check_idle_timeout_seconds)
            except (Abort, KeyboardInterrupt) as exc:
                failure = exc
            after, _ = worktree_fingerprint(w.root)
            after_paths = worktree_inventory(w.root)
            changed = before != after or before_paths != after_paths
            if changed:
                self._invalidate_verification()
                self._report_check_changes(before_paths, after_paths,
                                           phase=f"CHECK PASS {attempt} UNSTABLE")
            if current_branch(w.root) != branch or head(w.root) != starting_head:
                self._invalidate_verification()
                raise Abort("CHECK_HEAD_DRIFT: Branch or HEAD changed during verification")
            if failure is not None:
                if whitespace_warnings and isinstance(failure, Abort):
                    details = "\n    Additional Git whitespace warnings:\n" + "\n".join(
                        f"      {line}" for line in whitespace_warnings[:3])
                    raise Abort(f"{failure}{details}") from failure
                raise failure
            if changed:
                if policy == "recheck_once" and attempt == 1:
                    if before_retry is not None:
                        before_retry(before_paths, after_paths)
                    print("==> CHECKS: first pass changed bytes; running the full set once more")
                    continue
                raise CheckWorktreeChanged(
                    "CHECKS_CHANGED_WORKTREE: Verification was not stable; "
                    "review the preserved changes and rerun CHK explicitly.")
            print(check_result_label(
                f"==> CHECK PASS {attempt}: STABLE (Git index and worktree bytes)",
                stable=True))
            break
        if head(w.root) != (w.record.get("before_patch_head") or head(w.root)):
            print("WARNING: HEAD has changed since patch application.")
        _, paths = worktree_fingerprint(w.root)
        if paths:
            w.record.update(phase="verified", verified_fingerprint=after,
                            verified_head=head(w.root), verified_branch=branch)
        else:
            w.record["verified_commit"] = head(w.root)
        w.persist()
        print("Canonical checks passed for the current worktree snapshot.")
        return True

    def _pending(self, branch):
        w = self.w
        return [(key, record) for key, record in w.state["workflows"].items()
                if isinstance(record, dict)
                and record.get("repository") == str(w.root.resolve())
                and record.get("phase") in PENDING_PHASES
                and (record.get("applied_branch") == branch or key == w.key)]

    def guarded_check(self, session_id: str, *, accepted_manual_paths=()):
        """Stage only explicitly owned paths, then freeze a successful CHK snapshot.

        This internal API is not a legacy CLI action. A future goal planner
        must obtain path-specific manual acceptance outside skipApproves.
        """
        w = self.w
        w.record.pop("guarded_verification", None)
        macro_policy = bool(getattr(w, "_macro_check_policy", False))
        if macro_policy:
            self._prepare_macro_checks()
        scope = inspect_commit_scope(w, session_id,
                                     accepted_manual_paths=accepted_manual_paths)
        assert_scope_unchanged(w, scope)
        run(["git", "add", "-A", "--", *scope.paths], w.root)
        staged_paths = status_paths(w.root)
        if (set(staged_paths) != set(scope.paths)
                or changed_contents_fingerprint(w.root, staged_paths)
                != scope.contents_fingerprint):
            raise NeedsVerification(
                "NEEDS_VERIFICATION: Files changed while staging the authorized scope; "
                "the existing index is preserved")
        staged = inspect_commit_scope(w, session_id,
                                      accepted_manual_paths=scope.accepted_manual)

        def restage_owned_changes(before, after):
            nonlocal staged
            if self._symlink_identity_changed(before, after):
                raise NeedsVerification("NEEDS_VERIFICATION: Symlink identity changed during "
                                        "checks; review it before staging")
            if any(before.get(name) is not None and after.get(name) is not None
                   and before[name].index != after[name].index
                   for name in before.keys() & after.keys()):
                raise NeedsVerification("NEEDS_VERIFICATION: Git index changed during checks; "
                                        "inspect staged changes before retrying")
            updated = inspect_commit_scope(w, session_id,
                                           accepted_manual_paths=scope.accepted_manual)
            if updated.paths != staged.paths:
                raise NeedsVerification("NEEDS_VERIFICATION: Check output changed the authorized "
                                        "commit path set; review the preserved files")
            run(["git", "add", "-A", "--", *staged.paths], w.root)
            staged = inspect_commit_scope(w, session_id,
                                          accepted_manual_paths=scope.accepted_manual)

        self.verify(macro_policy=macro_policy,
                    before_retry=restage_owned_changes if macro_policy else None)
        stable = inspect_commit_scope(w, session_id,
                                      accepted_manual_paths=scope.accepted_manual)
        if stable != staged:
            raise NeedsVerification(
                "NEEDS_VERIFICATION: Commit scope changed during canonical checks")
        if run(["git", "diff", "--quiet"], w.root, check=False).returncode:
            raise NeedsVerification(
                "NEEDS_VERIFICATION: Checked working-tree bytes differ from the staged index")
        w.record["guarded_verification"] = {
            "session_id": session_id, "branch": stable.branch, "head": stable.head,
            "fingerprint": stable.fingerprint, "policy_fingerprint": stable.policy_fingerprint,
            "paths": list(stable.paths), "accepted_manual": list(stable.accepted_manual),
        }
        w.persist()
        print(f"Guarded CHK verified {len(stable.paths)} explicitly scoped path(s).")
        return True

    def guarded_commit(self, session_id: str):
        """Commit the exact verified index; never stage additional files at CMT."""
        from .code_review import require_fresh_review
        require_fresh_review(self.w)
        w = self.w
        evidence = w.record.get("guarded_verification")
        if not isinstance(evidence, dict) or evidence.get("session_id") != session_id:
            raise NeedsVerification(
                "NEEDS_VERIFICATION: Run internal guarded CHK before a planned commit")
        scope = inspect_commit_scope(w, session_id,
                                     accepted_manual_paths=evidence.get("accepted_manual", ()))
        expected = {
            "session_id": scope.session_id, "branch": scope.branch, "head": scope.head,
            "fingerprint": scope.fingerprint, "policy_fingerprint": scope.policy_fingerprint,
            "paths": list(scope.paths), "accepted_manual": list(scope.accepted_manual),
        }
        if evidence != expected or (w.record.get("verified_fingerprint") != scope.fingerprint
                                    or w.record.get("verified_head") != scope.head
                                    or w.record.get("verified_branch") != scope.branch):
            raise NeedsVerification(
                "NEEDS_VERIFICATION: Verified Git bytes, branch, HEAD, or check policy are stale")
        if run(["git", "diff", "--quiet"], w.root, check=False).returncode:
            raise NeedsVerification(
                "NEEDS_VERIFICATION: Unstaged edits remain after guarded CHK")
        staged_data = run(["git", "diff", "--cached", "--name-only", "-z"],
                          w.root, text=False).stdout
        staged_paths = {os.fsdecode(item) for item in staged_data.split(b"\x00") if item}
        if staged_paths != set(scope.paths):
            raise NeedsVerification(
                "NEEDS_VERIFICATION: The staged commit scope differs from verified paths")
        run(["git", "diff", "--cached", "--check"], w.root)
        assert_scope_unchanged(w, scope)
        expected_tree = output(["git", "write-tree"], w.root)
        assert_scope_unchanged(w, scope)
        run(["git", "commit", "-F", "-"], w.root, input_text=w.handoff.message,
            log_commit_message=w.handoff.message)
        committed_sha = head(w.root)
        if output(["git", "rev-parse", "HEAD^{tree}"], w.root) != expected_tree:
            raise Abort(
                "COMMIT_CONTENT_DRIFT: Git hooks changed the committed tree; "
                "inspect the new commit before recording successful publication")
        pending = self._pending(scope.branch)
        for key, record in pending:
            if record.get("session_id") != session_id:
                raise Abort("Committed session contains an unexpected pending workflow")
            record.update(phase="committed", commit_sha=committed_sha,
                          applied_branch=scope.branch, combined_commit=True)
            record.pop("guarded_verification", None)
        record_session_commit(w.state, session_id, committed_sha)
        w.persist()
        with locked_history(w.config.applied_patches_path) as history:
            for _, record in pending:
                history.record_commit_branch(record["patch_file"],
                                             record["branch"], scope.branch)
        print(f"Guarded commit {committed_sha}; no push or PR operation was requested.")
        return True

    def commit(self):
        from .code_review import require_fresh_review
        require_fresh_review(self.w)
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
        return True

    def push(self):
        w = self.w
        branch = self.branch()
        current_sha = head(w.root)
        if getattr(w, "_goal_guarded_publication", False):
            if (branch != w.handoff.branch or w.phase != "committed"
                    or w.record.get("commit_sha") != current_sha):
                raise Abort("PUBLICATION_COMMIT_DRIFT: Guarded push requires the exact feature commit")
            if status_paths(w.root):
                raise Abort("PUBLICATION_DIRTY_WORKTREE: Guarded push requires a clean checkout")
            if w.record.get("remote_url") != output(
                    ["git", "remote", "get-url", w.config.remote], w.root):
                raise Abort("PUBLICATION_REMOTE_DRIFT: Recorded push remote differs from Git")
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
            run(["git", "fetch", "--no-tags", w.config.remote, f"refs/heads/{branch}"],
                w.root, timeout=w.config.github_timeout_seconds)
            ancestor = run(["git", "merge-base", "--is-ancestor", remote, current_sha],
                           w.root, check=False)
            if ancestor.returncode != 0:
                raise Abort("Remote branch is not an ancestor; LOOSE never force-pushes history")
        if remote != current_sha:
            if not confirm(f"Push committed HEAD {current_sha} to {w.config.remote}/{branch}?"):
                return
            run(["git", "push", "-u", w.config.remote, f"HEAD:refs/heads/{branch}"],
                w.root, timeout=w.config.github_timeout_seconds)
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
        if remote == current_sha and not updated:
            return ActionResult.already_satisfied("Remote branch already matches committed HEAD")
        return True

    def pr(self):
        return self.w.force_actions.pr()

    def merge(self):
        return self.w.force_actions.merge()

    def sync(self):
        return self.w.force_actions.sync()

