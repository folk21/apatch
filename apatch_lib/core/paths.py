"""One authority for reserved repository-local runtime paths."""

RUNTIME_DIRECTORY = ".apatch"
REGISTRY_MEMBER = f"{RUNTIME_DIRECTORY}/created_patches.txt"
PARAMS_MEMBER = f"{RUNTIME_DIRECTORY}/params.json"
BACKUPS_DIRECTORY = f"{RUNTIME_DIRECTORY}/backups"
RUNTIME_METADATA_MEMBERS = frozenset({REGISTRY_MEMBER, PARAMS_MEMBER})


def is_protected_runtime_path(relative: str) -> bool:
    """Reject ZIP source edits to local policy, checkpoints, and runtime state."""
    return relative == RUNTIME_DIRECTORY or relative.startswith(RUNTIME_DIRECTORY + "/")


def runtime_ignore_patterns() -> dict[str, str]:
    """Git exclude patterns for the stable generated runtime paths."""
    paths = (BACKUPS_DIRECTORY, REGISTRY_MEMBER, PARAMS_MEMBER)
    return {path: f"/{path}" for path in paths} | {
        f"{path}.lock": f"/{path}.lock"
        for path in (REGISTRY_MEMBER, PARAMS_MEMBER)
    }
