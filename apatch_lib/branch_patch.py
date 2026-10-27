"""Feature branch creation and patch extraction actions."""

import logging

from .branch_guard import assert_no_unfinished_feature_branches
from .created_patches import assert_patch_order, persist_registry
from .gitutil import (branch_exists, confirm, current_branch, head, remote_head,
                      require_branch, require_clean, run, skip_approvals_enabled,
                      worktree_fingerprint)
from .core.enums import WorkflowPhase
from .model import Abort
from .patch import apply, inspect
from .patch_history import locked_history


LOGGER = logging.getLogger("apatch.branch_patch")


class BranchPatchActions:
    """Bounded branch and patch operations sharing the Workflow checkpoint owner."""

    def __init__(self, workflow):
        self.workflow = workflow

    def assert_history_well_formed(self):
        """Validate the journal before any feature-branch switch or creation."""
        with locked_history(self.workflow.config.applied_patches_path):
            pass

    def assert_patch_order(self, history=None, archive=None):
        """Guard application using the authoritative applied-patch journal."""
        w = self.workflow
        if history is None:
            with locked_history(w.config.applied_patches_path) as locked:
                return self.assert_patch_order(locked, archive)
        archive = archive or inspect(w.config, w.handoff, w.root, before_apply=False)
        return assert_patch_order(w.root, w.handoff.patch, history, archive.created_registry)

    def assert_new_branch_available(self):
        """Reject existing local and remote refs, including non-checked-out branches."""
        w = self.workflow
        if branch_exists(w.root, w.handoff.branch):
            raise Abort(f"Feature branch already exists locally: {w.handoff.branch}")
        if remote_head(w.root, w.config, w.handoff.branch):
            raise Abort(f"Feature branch already exists on {w.config.remote}: {w.handoff.branch}")

    def new_branch(self, with_patch=False):
        w = self.workflow
        if with_patch:
            self.assert_patch_order()
        self.assert_history_well_formed()
        if w.phase != "new":
            raise Abort("Feature branch has already been prepared for this patch")
        require_clean(w.root)
        if current_branch(w.root) != w.config.base:
            raise Abort(f"Create a feature branch only from {w.config.base}")
        self.assert_new_branch_available()
        w.assert_base()
        remote_url = w.assert_remote_unchanged()
        if remote_head(w.root, w.config, w.config.base) != head(w.root):
            raise Abort("Local base HEAD differs from the configured remote base branch")
        archive = w.assert_patch_identity() if with_patch else None
        if with_patch:
            with locked_history(w.config.applied_patches_path) as history:
                self.assert_patch_order(history, archive)
                if not self.warn_if_previously_applied(history):
                    return
                if not confirm(f"Create branch {w.handoff.branch} from current HEAD?"):
                    return
                self.assert_new_branch_available()
                assert_no_unfinished_feature_branches(w.root, w.config, w.handoff.branch)
                require_clean(w.root)
                w.assert_base()
                if remote_head(w.root, w.config, w.config.base) != head(w.root):
                    raise Abort("Remote base branch changed before branch creation")
                run(["git", "switch", "-c", w.handoff.branch], w.root)
                require_branch(w.root, w.handoff.branch)
                w.record.update(phase="branch_created", branch_base=head(w.root),
                                remote_url=remote_url, branch_origin="CREATED")
                w.persist()
                return self.unpack(archive, history=history, history_confirmed=True)
        else:
            if not confirm(f"Create branch {w.handoff.branch} from current HEAD?"):
                return
            self.assert_new_branch_available()
            assert_no_unfinished_feature_branches(w.root, w.config, w.handoff.branch)
            require_clean(w.root)
            w.assert_base()
            if remote_head(w.root, w.config, w.config.base) != head(w.root):
                raise Abort("Remote base branch changed before branch creation")
            run(["git", "switch", "-c", w.handoff.branch], w.root)
            require_branch(w.root, w.handoff.branch)
            w.record.update(phase="branch_created", branch_base=head(w.root),
                            remote_url=remote_url, branch_origin="CREATED")
            w.persist()
            return True

    def prepare_branch_after_apply(self):
        """Move verified uncommitted patch bytes from base to the planned feature branch."""
        w = self.workflow
        if (not w.record.get("zip_first") or w.phase != "patch_applied"
                or w.record.get("applied_branch") != w.config.base):
            raise Abort("Apply a self-contained ZIP on the base branch before BRN")
        self.assert_history_well_formed()
        expected_head = w.record.get("before_patch_head")
        if not expected_head or head(w.root) != expected_head:
            raise Abort("Base HEAD drifted after patch extraction; cannot move pending changes")
        if w.record.get("archive_sha256") != w.handoff.patch_sha256:
            raise Abort("Cached patch digest differs from the applied ZIP")
        w.assert_remote_unchanged()
        before_fingerprint, paths = w.assert_expected_paths()
        if not paths:
            raise Abort("No recorded patch changes to carry into the feature branch")
        branch = current_branch(w.root)
        if branch == w.handoff.branch:
            origin = "CREATED"
            print("Recovering a previously switched feature branch from live Git state.")
        else:
            if branch != w.config.base:
                raise Abort(f"BRN requires current branch {w.config.base} or {w.handoff.branch}")
            if remote_head(w.root, w.config, w.config.base) != expected_head:
                raise Abort("Remote base HEAD changed since patch extraction")
            self.assert_new_branch_available()
            if not confirm(f"Move uncommitted patch changes from {branch} to {w.handoff.branch}?"):
                return
            self.assert_new_branch_available()
            assert_no_unfinished_feature_branches(w.root, w.config, w.handoff.branch)
            if head(w.root) != expected_head or worktree_fingerprint(w.root)[0] != before_fingerprint:
                raise Abort("Base HEAD or pending files changed before branch creation")
            if remote_head(w.root, w.config, w.config.base) != expected_head:
                raise Abort("Remote base moved during branch preflight")
            run(["git", "switch", "-c", w.handoff.branch], w.root)
            origin = "CREATED"
        require_branch(w.root, w.handoff.branch)
        if head(w.root) != expected_head or worktree_fingerprint(w.root)[0] != before_fingerprint:
            raise Abort("Pending patch bytes changed during branch transition; inspect before retry")
        w.record.update(applied_branch=w.handoff.branch, branch_origin=origin,
                        branch_base=expected_head, extracted_on_branch=w.config.base)
        w.persist()
        with locked_history(w.config.applied_patches_path) as history:
            history.record_commit_branch(w.handoff.patch, w.handoff.branch, w.handoff.branch)
        print(f"Patch changes now reside on {w.handoff.branch}; run CHK next.")
        return True

    def warn_if_previously_applied(self, history):
        w = self.workflow
        if not history.contains(w.handoff.patch):
            return True
        LOGGER.warning("previously applied patch selected for reapplication name=%s", w.handoff.patch)
        print(f"WARNING: Patch {w.handoff.patch} is already in the applied-patch history.")
        if skip_approvals_enabled():
            raise Abort("Patch already applied; do not replay APL with skipApproves=true. "
                        "Resume the cached workflow with opSeq=CHK,STS without the ZIP "
                        "or followup=true. To intentionally reapply, run APL interactively "
                        "with skipApproves=false and confirm the duplicate.")
        try:
            response = input("Apply this patch again? [yes/no]: ").strip().lower()
        except EOFError as exc:
            raise Abort("Duplicate ZIP replay requires interactive confirmation; "
                        "skipApproves=true cannot authorize it") from exc
        if response not in {"yes", "no"}:
            raise Abort("Expected yes or no; patch was not applied")
        if response == "no":
            LOGGER.info("previously applied patch reapplication declined")
            return False
        LOGGER.warning("developer approved previously applied patch reapplication")
        return True

    def block_unattended_duplicate(self):
        """Reject replay before previous-cycle updates or overlap confirmation."""
        if not skip_approvals_enabled():
            return
        with locked_history(self.workflow.config.applied_patches_path) as history:
            self.warn_if_previously_applied(history)

    def unpack(self, archive=None, *, history=None, history_confirmed=False):
        w = self.workflow
        if history is None:
            with locked_history(w.config.applied_patches_path) as locked:
                return self.unpack(archive, history=locked)
        self.assert_patch_order(history, archive)
        if w.phase not in {WorkflowPhase.NEW, WorkflowPhase.BRANCH_CREATED}:
            raise Abort("Patch has already been applied or advanced")
        patch_branch = current_branch(w.root)
        if not patch_branch or patch_branch == "HEAD":
            raise Abort("Check out a named branch before applying a patch")
        archive = archive or w.assert_patch_identity()
        zip_first = archive.embedded_handoff is not None and patch_branch == w.config.base
        if w.config.require_patch_feature_branch and not zip_first:
            require_branch(w.root, w.handoff.branch)
        require_clean(w.root)
        remote_url = w.assert_remote_unchanged()
        if w.phase == "new":
            w.assert_base()
        elif patch_branch == w.handoff.branch:
            if head(w.root) != w.record.get("branch_base"):
                raise Abort("Feature branch HEAD drifted since branch creation")
        else:
            w.assert_base()
        remote_before_patch = remote_head(w.root, w.config, patch_branch)
        if w.phase == "branch_created" and patch_branch == w.handoff.branch and remote_before_patch is not None:
            raise Abort("Feature branch unexpectedly appeared on remote after local creation")
        if remote_before_patch is not None and remote_before_patch != head(w.root):
            raise Abort(f"Remote branch {patch_branch} differs from local HEAD")
        if not history_confirmed and not self.warn_if_previously_applied(history):
            return
        if not confirm(f"Apply {w.handoff.patch} to {patch_branch}?"):
            return
        if w.phase == "new":
            w.record["remote_url"] = remote_url
            w.record.setdefault("branch_origin", "REUSED")
        w.record.update(
            phase="applying",
            archive_sha256=archive.sha256,
            zip_first=zip_first,
            remote_before_patch_head=remote_before_patch,
            applied_branch=patch_branch,
            changed_paths=sorted(set(archive.changed) | set(w.handoff.delete_paths)),
            before_patch_head=head(w.root),
        )
        w.persist()
        apply(w.config, w.handoff, w.root, archive)
        w.assert_expected_paths()
        persist_registry(w.root, archive.created_registry)
        history.append(w.handoff.patch, w.handoff.branch, patch_branch)
        w.record["phase"] = "patch_applied"
        w.persist()
        print("Patch applied. Run verification before committing.")
        return True
