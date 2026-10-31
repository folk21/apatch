"""Build a self-contained patch ZIP only from a freshly verified source snapshot."""

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import zipfile

from .artifact_preflight import PreflightResult, preflight
from .core.paths import PARAMS_MEMBER, is_protected_runtime_path
from .gitutil import current_branch, head, output, worktree_fingerprint, worktree_inventory
from .model import (Abort, BASENAME_PATTERN, load_config, load_project_config,
                    parse_handoff_payload, safe_relative)


MAX_SOURCE_PATHS = 5000


@dataclass(frozen=True)
class PackagingResult:
    """Archive identity and the verified Git snapshot used to build it."""

    output: str
    zip_sha256: str
    size_bytes: int
    source: PreflightResult
    files: tuple[str, ...]
    deleted_paths: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"status": "passed", **asdict(self)}


def _output_path(raw: Path, root: Path) -> Path:
    if raw.is_symlink():
        raise Abort(f"ZIP output must not be a symlink: {raw}")
    parent = raw.expanduser().parent.resolve()
    output_path = parent / raw.name
    if not BASENAME_PATTERN.fullmatch(raw.name):
        raise Abort("ZIP output must have a safe ASCII .zip basename")
    if not parent.is_dir():
        raise Abort(f"ZIP output directory does not exist: {parent}")
    if parent == root or root in parent.parents:
        raise Abort("ZIP output must be outside the source Git repository")
    if output_path.exists() or output_path.is_symlink():
        raise Abort(f"ZIP output already exists; choose a new filename: {output_path}")
    return output_path


def _scope(included: tuple[str, ...], deleted: tuple[str, ...]
           ) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not included and not deleted:
        raise Abort("Packaging requires at least one --include or --delete path")
    if len(included) + len(deleted) > MAX_SOURCE_PATHS:
        raise Abort("Packaging exceeds the maximum number of source paths")
    normalized = [safe_relative(name) for name in (*included, *deleted)]
    if len(set(normalized)) != len(normalized):
        raise Abort("Duplicate or conflicting --include/--delete source paths")
    for name in normalized:
        if is_protected_runtime_path(name):
            raise Abort(f"Cannot package protected apatch path: {name}")
    for name in normalized:
        for index in range(1, name.count("/") + 1):
            ancestor = "/".join(name.split("/")[:index])
            if ancestor in normalized:
                raise Abort(f"Conflicting packaging paths: {ancestor} and {name}")
    return tuple(sorted(included)), tuple(sorted(deleted))


def _verify_source(root: Path, evidence: PreflightResult, stage: str) -> None:
    if current_branch(root) != evidence.branch or head(root) != evidence.head:
        raise Abort(f"Source Git branch or HEAD changed {stage}; ZIP was not published")
    digest, changed = worktree_fingerprint(root)
    if digest != evidence.worktree_sha256 or tuple(sorted(changed)) != evidence.changed_paths:
        raise Abort(f"Source changed {stage}; rerun preflight and packaging")


def _validate_scope(root: Path, evidence: PreflightResult,
                    included: tuple[str, ...], deleted: tuple[str, ...]) -> None:
    observed = set(evidence.changed_paths)
    selected = set(included) | set(deleted)
    if observed - selected:
        sample = ", ".join(repr(name) for name in sorted(observed - selected)[:5])
        raise Abort("Source has changed/untracked paths outside the packaging manifest: "
                    + sample + ". Use a dedicated source checkout or include all changes")
    if set(included) - observed:
        raise Abort("Included paths must be changed or untracked: "
                    + ", ".join(sorted(set(included) - observed)[:5]))
    for name in deleted:
        path = root / name
        if path.exists() or path.is_symlink():
            raise Abort(f"Declared deletion still exists in the source checkout: {name}")
        kind = output(["git", "cat-file", "-t", "HEAD:" + name], root)
        if kind != "blob":
            raise Abort(f"Deleted path is not a tracked file at HEAD: {name}")


def _read_source_file(root: Path, name: str, limit: int) -> tuple[bytes, int]:
    """Reject symlinks and bound the source bytes read into the archive."""
    current = root
    for part in name.split("/")[:-1]:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise Abort(f"Unsafe parent directory for packaged source: {name}")
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise Abort(f"Packaged source must be a regular non-symlink file: {name}")
    if not hasattr(os, "O_NOFOLLOW"):
        raise Abort("Secure patch packaging requires O_NOFOLLOW support")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise Abort(f"Non-regular or oversized packaged source: {name}")
            data = stream.read(limit + 1)
    except OSError as exc:
        raise Abort(f"Cannot safely read packaged source {name}: {exc}") from exc
    if len(data) > limit:
        raise Abort(f"Packaged source exceeds size limit: {name}")
    mode = 0o755 if info.st_mode & 0o111 else 0o644
    return data, mode


def _member(name: str, mode: int) -> zipfile.ZipInfo:
    item = zipfile.ZipInfo(name)
    item.create_system = 3
    item.external_attr = ((stat.S_IFREG | mode) << 16)
    item.compress_type = zipfile.ZIP_DEFLATED
    return item


def pack_source(project: Path, installation: Path, destination: Path, *,
                branch: str, message: str, included: tuple[str, ...],
                deleted: tuple[str, ...] = (), prepare: bool = False,
                base_commit: str | None = None) -> PackagingResult:
    """Verify, package, re-verify, then publish an exclusive ZIP in one call."""
    root = project.resolve()
    included, deleted = _scope(included, deleted)
    target = _output_path(destination, root)
    payload = {
        "schema_version": 1,
        "repository": root.name,
        "feature_branch": branch,
        "patch_file": target.name,
        "commit_message": message,
        "base_commit": base_commit,
    }
    if deleted:
        payload["delete_paths"] = list(deleted)
    parse_handoff_payload(payload, embedded=True)

    evidence = preflight(root, installation, prepare=prepare)
    _verify_source(root, evidence, "after preflight")
    _validate_scope(root, evidence, included, deleted)
    source_inventory = worktree_inventory(root)
    config_limit = _max_archive_bytes(root, installation)
    size = 0
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".apatch-pack-", suffix=".tmp",
                                         dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9) as archive:
            for name in included:
                content, mode = _read_source_file(root, name, config_limit - size)
                expected = source_inventory.get(name)
                if (expected is None or expected.kind != "file"
                        or hashlib.sha256(content).hexdigest() != expected.bytes_sha256
                        or bool(mode & 0o111) != expected.executable):
                    raise Abort(f"Packaged source bytes or mode changed after verification: {name}")
                size += len(content)
                archive.writestr(_member(f"{root.name}/{name}", mode), content)
            metadata = (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   indent=2) + "\n").encode("utf-8")
            size += len(metadata)
            if size > config_limit or len(metadata) > 65536:
                raise Abort("ZIP content exceeds the configured project archive limit")
            archive.writestr(_member(f"{root.name}/{PARAMS_MEMBER}", 0o600), metadata)

        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise Abort("Newly built ZIP failed integrity verification")
            expected_names = {f"{root.name}/{name}" for name in included}
            expected_names.add(f"{root.name}/{PARAMS_MEMBER}")
            if set(archive.namelist()) != expected_names:
                raise Abort("ZIP members differ from the explicitly approved source manifest")

        _verify_source(root, evidence, "during ZIP creation")
        if temporary.stat().st_size > config_limit:
            raise Abort("Compressed ZIP exceeds the configured archive size limit")
        zip_digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        _verify_source(root, evidence, "before ZIP publication")
        try:
            os.link(temporary, target)
        except OSError as exc:
            raise Abort(f"Cannot publish ZIP exclusively at {target}: {exc}") from exc
        return PackagingResult(str(target), zip_digest, target.stat().st_size,
                               evidence, included, deleted)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _max_archive_bytes(root: Path, installation: Path) -> int:
    return load_project_config(root, load_config(installation)).max_bytes
