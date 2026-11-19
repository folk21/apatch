"""Published Git read-only API; legacy command runner is not a new public port."""

from ..gitutil import (current_branch, head, repository_root,
                       status_paths, worktree_fingerprint)
from .inspection import (index_entries, inspect_repository, inspect_worktree,
                         worktree_change_details, worktree_inventory)
from .models import RepositorySnapshot, WorktreeEntry, WorktreeSnapshot

__all__ = (
    "RepositorySnapshot", "WorktreeEntry", "WorktreeSnapshot",
    "inspect_repository", "inspect_worktree", "index_entries", "worktree_inventory",
    "worktree_change_details", "current_branch", "head",
    "repository_root", "status_paths", "worktree_fingerprint",
)

