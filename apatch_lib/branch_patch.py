"""Feature branch creation and patch extraction actions."""

import logging

from .branch_guard import assert_no_unfinished_feature_branches
from .gitutil import (branch_exists, confirm, current_branch, head, remote_head,
                      require_branch, require_clean, run, skip_approvals_enabled)
from .model import Abort
from .patch import apply
from .patch_history import locked_history


LOGGER = logging.getLogger("apatch.branch_patch")


class BranchPatchActions:
    """Bounded branch and patch operations sharing the Workflow checkpoint owner."""

    def __init__(self, workflow):
        self.workflow = workflow

    def assert_new_branch_available(self):
        """Reject existing local and remote refs, including non-checked-out branches."""
        w = self.workflow
        if branch_exists(w.root, w.handoff.branch):
            raise Abort(f"Feature branch already exists locally: {w.handoff.branch}")
        if remote_head(w.root, w.config, w.handoff.branch):
            raise Abort(f"Feature branch already exists on {w.config.remote}: {w.handoff.branch}")

    def new_branch(self, with_patch=False):
        w = self.workflow
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
                self.unpack(archive, history=history, history_confirmed=True)
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

    def warn_if_previously_applied(self, history):
        w = self.workflow
        if not history.contains(w.handoff.patch):
            return True
        LOGGER.warning("previously applied patch selected for reapplication name=%s", w.handoff.patch)
        print(f"WARNING: Patch {w.handoff.patch} is already in the applied-patch history.")
        if skip_approvals_enabled():
            print("Duplicate patch reapplication [auto-approved: skipApproves=true]")
            LOGGER.warning("duplicate patch reapplication auto-approved")
            return True
        try:
            response = input("Apply this patch again? [yes/no]: ").strip().lower()
        except EOFError as exc:
            raise Abort("Interactive confirmation required; use skipApproves=true to automate approvals") from exc
        if response not in {"yes", "no"}:
            raise Abort("Expected yes or no; patch was not applied")
        if response == "no":
            LOGGER.info("previously applied patch reapplication declined")
            return False
        LOGGER.warning("developer approved previously applied patch reapplication")
        return True

    def unpack(self, archive=None, *, history=None, history_confirmed=False):
        w = self.workflow
        if history is None:
            with locked_history(w.config.applied_patches_path) as locked:
                return self.unpack(archive, history=locked)
        if w.phase not in {"new", "branch_created"}:
            raise Abort("Patch has already been applied or advanced")
        patch_branch = current_branch(w.root)
        if not patch_branch or patch_branch == "HEAD":
            raise Abort("Check out a named branch before applying a patch")
        if w.config.require_patch_feature_branch:
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
        archive = archive or w.assert_patch_identity()
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
            remote_before_patch_head=remote_before_patch,
            applied_branch=patch_branch,
            changed_paths=sorted(set(archive.changed) | set(w.handoff.delete_paths)),
            before_patch_head=head(w.root),
        )
        w.persist()
        apply(w.config, w.handoff, w.root, archive)
        w.assert_expected_paths()
        history.append(w.handoff.patch, w.handoff.branch, patch_branch)
        w.record["phase"] = "patch_applied"
        w.persist()
        print("Patch applied. Run verification before committing.")
