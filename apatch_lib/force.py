"""Explicit recovery actions backed by live Git evidence and audit checkpoints."""

import logging
import zipfile
from dataclasses import replace
from datetime import datetime, timezone

from . import github
from .gitutil import (branch_exists, confirm, current_branch, head, output, remote_head,
                      require_clean, run, worktree_fingerprint)
from .model import Abort
from .patch import apply, inspect, patch_file
from .patch_history import locked_history


LOGGER = logging.getLogger("apatch.force")


class ForceActions:
    """Bypass stale workflow phases, but never override Git history or file safety."""

    def __init__(self, workflow):
        self.w = workflow

    def branch(self):
        name = current_branch(self.w.root)
        if not name or name == "HEAD":
            raise Abort("FORCE requires a checked-out named branch")
        return name

    def remote_url(self):
        return output(["git", "remote", "get-url", self.w.config.remote], self.w.root)

    def previous_remote_head(self, branch):
        try:
            return remote_head(self.w.root, self.w.config, branch)
        except Abort:
            LOGGER.warning("FORCE remote branch unavailable during local recovery branch=%s", branch)
            return None

    def archive(self, *, before_apply=False):
        return inspect(self.w.config, self.w.handoff, self.w.root, before_apply=before_apply)

    def checkpoint(self, phase, action, **fields):
        w = self.w
        previous = w.phase
        if phase in {"branch_created", "applying", "patch_applied", "verified"}:
            for key in ("verified_fingerprint", "verified_commit", "commit_sha", "pushed_sha",
                        "pr_number"):
                w.record.pop(key, None)
        elif phase == "committed":
            for key in ("verified_commit", "pushed_sha", "pr_number"):
                w.record.pop(key, None)
        elif phase == "pushed" and w.record.get("pushed_sha") != fields.get("pushed_sha"):
            w.record.pop("pr_number", None)
        w.record.update(fields)
        w.record["phase"] = phase
        events = w.record.setdefault("force_events", [])
        if not isinstance(events, list):
            raise Abort("Invalid force checkpoint history")
        events.append({"action": action, "from_phase": previous, "to_phase": phase,
                       "head": head(w.root), "utc": datetime.now(timezone.utc).isoformat()})
        del events[:-50]
        w.persist()
        LOGGER.warning("FORCE state reconciled action=%s phase=%s->%s branch=%s",
                       action, previous, phase, w.record.get("applied_branch"))

    def prepare_branch(self, with_patch=False):
        w = self.w
        require_clean(w.root)
        current = self.branch()
        target = w.handoff.branch
        if branch_exists(w.root, target):
            if current == target:
                question = f"Adopt the already checked-out branch {target}?"
            else:
                question = f"Switch from {current} to existing branch {target}?"
            if not confirm("FORCE: " + question):
                return
            if current != target:
                run(["git", "switch", target], w.root)
        else:
            remote_commit = self.previous_remote_head(target)
            if remote_commit:
                if not confirm(f"FORCE: Fetch and track existing {w.config.remote}/{target} at {remote_commit}?"):
                    return
                run(["git", "fetch", "--no-tags", w.config.remote,
                     f"refs/heads/{target}:refs/remotes/{w.config.remote}/{target}"], w.root)
                run(["git", "switch", "--track", "-c", target,
                     f"{w.config.remote}/{target}"], w.root)
            else:
                if not confirm(f"FORCE: Create {target} from current branch {current} at {head(w.root)}?"):
                    return
                run(["git", "switch", "-c", target], w.root)
        self.checkpoint("branch_created", "branch prepared", applied_branch=target,
                        branch_base=head(w.root), remote_url=self.remote_url(),
                        remote_before_patch_head=self.previous_remote_head(target))
        if with_patch:
            self.apply_or_adopt()

    def _matches_archive_files(self, archive):
        """Detect an already committed patch without writing any worktree files."""
        w = self.w
        try:
            with zipfile.ZipFile(patch_file(w.config, w.handoff)) as source:
                for item in source.infolist():
                    if item.is_dir():
                        continue
                    relative = item.filename.split("/", 1)[1]
                    if (w.root / relative).read_bytes() != source.read(item):
                        return False
        except OSError:
            return False
        return all(not (w.root / relative).exists() for relative in w.handoff.delete_paths)

    def _commit_paths(self):
        raw = run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD"],
                  self.w.root).stdout
        return set(filter(None, raw.split("\x00")))

    def _adopt_commit(self, *, require_archive_match=False):
        w = self.w
        branch = self.branch()
        require_clean(w.root)
        current = head(w.root)
        if w.record.get("commit_sha") == current and w.record.get("applied_branch") == branch:
            return True
        archive = self.archive()
        paths = self._commit_paths()
        expected = set(archive.changed) | set(w.handoff.delete_paths)
        if not paths or not expected.intersection(paths):
            raise Abort("Cannot associate HEAD with this patch: its last commit changes no patch paths")
        matches = self._matches_archive_files(archive)
        if require_archive_match and not matches:
            return False
        print(f"FORCE: current HEAD {current} on {branch} changes {len(paths)} path(s).")
        if not matches:
            print("WARNING: The committed files differ from the ZIP. The recorded patch will be a manual override.")
        if not confirm("Adopt this existing commit as the patch's commit?"):
            return False
        parent = output(["git", "rev-parse", "HEAD^"], w.root)
        self.checkpoint("committed", "manual commit adopted", applied_branch=branch,
                        before_patch_head=parent, commit_sha=current, changed_paths=sorted(paths),
                        archive_sha256=archive.sha256, remote_url=self.remote_url(),
                        remote_before_patch_head=self.previous_remote_head(branch),
                        manually_adopted=not matches)
        return True

    def _adopt_changes(self, archive, fingerprint, paths):
        w = self.w
        branch = self.branch()
        expected = set(archive.changed) | set(w.handoff.delete_paths)
        manual_override = set(paths) != expected or not self._matches_archive_files(archive)
        if manual_override:
            print("WARNING: Worktree paths or file contents differ from the ZIP. "
                  "This will be recorded as a manual override.")
        print("FORCE: adopt these existing changes without extracting or overwriting files:")
        for path, status in sorted(paths.items()):
            print(f"  {status} {path}")
        if not confirm("Associate ALL listed changes with this patch?"):
            return False
        preserved_verification = (w.record.get("verified_fingerprint") == fingerprint
                                  and w.record.get("before_patch_head") == head(w.root)
                                  and w.record.get("applied_branch") == branch)
        phase = "verified" if preserved_verification else "patch_applied"
        self.checkpoint(phase, "manual worktree adopted", applied_branch=branch,
                        before_patch_head=head(w.root), changed_paths=sorted(paths),
                        archive_sha256=archive.sha256, remote_url=self.remote_url(),
                        remote_before_patch_head=self.previous_remote_head(branch),
                        manually_adopted=manual_override)
        with locked_history(w.config.applied_patches_path) as history:
            history.append(w.handoff.patch)
        return True

    def apply_or_adopt(self):
        w = self.w
        branch = self.branch()
        fingerprint, paths = worktree_fingerprint(w.root)
        if paths:
            archive = self.archive()
            if self._adopt_changes(archive, fingerprint, paths):
                print("Existing worktree changes recorded. Run canonical checks when ready.")
            return
        archive = self.archive(before_apply=True)
        if self._matches_archive_files(archive) and (set(archive.changed) |
                                                    set(w.handoff.delete_paths)) & self._commit_paths():
            if self._adopt_commit(require_archive_match=True):
                print("The patch is already committed; no files were overwritten.")
            return
        with locked_history(w.config.applied_patches_path) as history:
            if not w.branch_patch.warn_if_previously_applied(history):
                return
            if not confirm(f"FORCE: Apply ZIP {w.handoff.patch} to clean branch {branch}?"):
                return
            self.checkpoint("applying", "apply started", applied_branch=branch,
                            before_patch_head=head(w.root), archive_sha256=archive.sha256,
                            changed_paths=sorted(set(archive.changed) | set(w.handoff.delete_paths)),
                            remote_url=self.remote_url(),
                            remote_before_patch_head=self.previous_remote_head(branch),
                            manually_adopted=False)
            apply(w.config, w.handoff, w.root, archive)
            fingerprint, paths = worktree_fingerprint(w.root)
            if set(paths) != set(w.record["changed_paths"]):
                raise Abort("Applied ZIP produced unexpected changes; inspect worktree manually")
            history.append(w.handoff.patch)
            self.checkpoint("patch_applied", "apply completed")
            print("Patch applied in FORCE mode. Run checks before publishing if possible.")

    def _ensure_dirty_snapshot(self):
        w = self.w
        fingerprint, paths = worktree_fingerprint(w.root)
        if not paths:
            return None
        if (w.record.get("applied_branch") == self.branch()
                and w.record.get("before_patch_head") == head(w.root)
                and set(w.record.get("changed_paths", [])) == set(paths)):
            return fingerprint, paths
        if not self._adopt_changes(self.archive(), fingerprint, paths):
            return None
        return fingerprint, paths

    def verify(self):
        w = self.w
        dirty = self._ensure_dirty_snapshot()
        if dirty is None:
            if worktree_fingerprint(w.root)[1]:
                return
            if not self._adopt_commit():
                return
            expected_head = head(w.root)
            phase = w.phase
        else:
            expected_head = head(w.root)
            phase = "verified"
        if not w.config.checks:
            raise Abort("No project verification commands configured")
        for command in w.config.checks:
            run(list(command), w.root, stream_output=True)
        if head(w.root) != expected_head:
            raise Abort("HEAD changed while running project verification")
        if dirty is not None:
            after, _ = worktree_fingerprint(w.root)
            if after != dirty[0]:
                self.checkpoint("patch_applied", "checks changed worktree")
                raise Abort("Checks modified project files; verification invalidated")
            self.checkpoint(phase, "canonical checks passed", verified_fingerprint=after)
        else:
            require_clean(w.root)
            self.checkpoint(phase, "post-commit checks passed", verified_commit=expected_head)
        print("Canonical checks passed; FORCE state synchronized with the current Git revision.")

    def commit_push(self):
        w = self.w
        dirty = self._ensure_dirty_snapshot()
        if dirty is None:
            if worktree_fingerprint(w.root)[1]:
                return
            if not self._adopt_commit():
                return
            return self._push_recorded_commit()
        fingerprint, paths = dirty
        branch = self.branch()
        print("FORCE: commit these changed paths:")
        for path, status in sorted(paths.items()):
            print(f"  {status} {path}")
        print("Commit message:\n" + w.handoff.message)
        if not confirm(f"Commit these paths on branch {branch} without requiring a verified phase?"):
            return
        if worktree_fingerprint(w.root)[0] != fingerprint:
            raise Abort("Working tree changed before staging")
        before = head(w.root)
        run(["git", "add", "-A"], w.root)
        staged = set(filter(None, run(["git", "diff", "--cached", "--name-only", "-z"],
                                      w.root).stdout.split("\x00")))
        if staged != set(paths):
            raise Abort("Staged paths do not match the reviewed worktree")
        if not confirm("Staged paths match; create this commit?"):
            return
        run(["git", "commit", "-F", "-"], w.root, input_text=w.handoff.message,
            log_commit_message=w.handoff.message)
        committed = head(w.root)
        if output(["git", "rev-parse", "HEAD^"], w.root) != before:
            raise Abort("Unexpected commit parent after FORCE commit")
        require_clean(w.root)
        self.checkpoint("committed", "commit created", applied_branch=branch,
                        before_patch_head=before, commit_sha=committed, remote_url=self.remote_url())
        self._push_recorded_commit()

    def _push_recorded_commit(self):
        w = self.w
        require_clean(w.root)
        branch = self.branch()
        current = head(w.root)
        if w.record.get("commit_sha") != current or w.record.get("applied_branch") != branch:
            if not self._adopt_commit():
                return
        remote = remote_head(w.root, w.config, branch)
        if remote == current:
            self.checkpoint("pushed", "existing remote push adopted", pushed_sha=current,
                            remote_url=self.remote_url())
            print(f"Remote {w.config.remote}/{branch} already matches {current}.")
            return
        if remote:
            run(["git", "fetch", "--no-tags", w.config.remote, f"refs/heads/{branch}"], w.root)
            result = run(["git", "merge-base", "--is-ancestor", remote, current], w.root,
                         check=False)
            if result.returncode != 0:
                raise Abort("Remote branch has diverged; FORCE never rewrites remote history")
        if not confirm(f"FORCE: Push {current} to {w.config.remote}/{branch} (fast-forward only)?"):
            return
        run(["git", "push", "-u", w.config.remote, f"HEAD:refs/heads/{branch}"], w.root)
        if remote_head(w.root, w.config, branch) != current:
            raise Abort("Remote HEAD does not match local HEAD after push")
        self.checkpoint("pushed", "push completed", pushed_sha=current,
                        remote_url=self.remote_url())
        print("FORCE push completed and verified against the remote branch.")

    def push(self):
        require_clean(self.w.root)
        if not self._adopt_commit():
            return
        self._push_recorded_commit()

    def _effective_handoff(self):
        branch = (self.w.record.get("applied_branch")
                  or (self.w.handoff.branch if current_branch(self.w.root) == self.w.config.base
                      else self.branch()))
        if branch == self.w.config.base:
            raise Abort("Cannot open or merge a PR from the base branch into itself")
        return replace(self.w.handoff, branch=branch)

    def _ensure_pushed(self):
        w = self.w
        handoff = self._effective_handoff()
        local = head(w.root)
        if current_branch(w.root) != handoff.branch:
            raise Abort(f"Check out the patch branch {handoff.branch} before FORCE PR operations")
        require_clean(w.root)
        if remote_head(w.root, w.config, handoff.branch) != local:
            raise Abort("PR creation requires the patch branch to be pushed with matching HEAD")
        if w.record.get("pushed_sha") != local:
            if not self._adopt_commit():
                return None
            self.checkpoint("pushed", "manual push reconciled", pushed_sha=local)
        return handoff

    def pr(self):
        w = self.w
        handoff = self._ensure_pushed()
        if handoff is None:
            return
        github.create_pr(w.config, handoff, w.root, w.record, w.persist)

    def _recover_pr(self, *, must_be_merged=False):
        w = self.w
        handoff = self._effective_handoff()
        repo = github.repository(w.config, w.root)
        prs = github.pr_list(w.config, w.root, repo, handoff.branch)
        matching = [item for item in prs if item["state"] in ({"MERGED"} if must_be_merged
                                                       else {"OPEN", "MERGED"})]
        if len(matching) != 1:
            raise Abort("Expected one matching GitHub PR; resolve missing or ambiguous PR manually")
        pr = matching[0]
        if pr["state"] == "OPEN":
            if remote_head(w.root, w.config, handoff.branch) != pr["headRefOid"]:
                raise Abort("Open PR points to a different remote branch revision")
            self.checkpoint("pr_created", "GitHub PR adopted", applied_branch=handoff.branch,
                            pr_number=pr["number"], pushed_sha=pr["headRefOid"])
        else:
            details = github.pr_details(w.root, repo, pr["number"])
            if details["state"] != "MERGED" or not details.get("mergedAt"):
                raise Abort("GitHub does not confirm PR merge")
            self.checkpoint("merged", "GitHub merge adopted", applied_branch=handoff.branch,
                            pr_number=pr["number"])
        return handoff, pr

    def merge(self):
        w = self.w
        handoff, pr = self._recover_pr()
        if pr["state"] == "OPEN":
            github.merge_pr(w.config, handoff, w.root, w.record, w.persist)
        if w.phase == "merged":
            github.sync_base(w.config, handoff, w.root, w.record, w.persist)

    def sync(self):
        w = self.w
        handoff, _ = self._recover_pr(must_be_merged=True)
        github.sync_base(w.config, handoff, w.root, w.record, w.persist)
