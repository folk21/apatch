"""Stage and apply inspected ZIP bytes through anchored directory descriptors."""

import hashlib
import io
import logging
import os
import secrets
import stat
import zipfile
from contextlib import contextmanager
from pathlib import Path

from ..mo_configuration.models import Config
from ..mo_core.api import Abort
from ..mo_core.paths import RUNTIME_METADATA_MEMBERS
from .inspection import inspect, patch_file
from .models import Archive, Handoff

LOGGER = logging.getLogger("apatch.patch")

_DIRECTORY_FLAGS = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0))


def _require_anchored_io() -> None:
    """Refuse hosts that cannot prevent path traversal during ZIP mutations."""
    required = (os.open, os.mkdir, os.stat, os.unlink)
    if (os.name != "posix" or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
            or not all(operation in os.supports_dir_fd for operation in required)):
        raise Abort("Safe ZIP extraction requires POSIX dir_fd and O_NOFOLLOW support")


@contextmanager
def _parent_fd(root_fd: int, relative: str, *, create: bool = False):
    """Traverse each parent without following symlinks or changing the root anchor."""
    descriptor = os.dup(root_fd)
    try:
        for component in relative.split("/")[:-1]:
            if create:
                try:
                    os.mkdir(component, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _destination_mode(parent_fd: int, name: str, relative: str) -> int | None:
    """Inspect only the directory entry; never follow its symlink target."""
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise Abort(f"Unsafe destination during ZIP extraction: {relative}")
    return stat.S_IMODE(info.st_mode)


def _new_temp(parent_fd: int) -> tuple[int, str]:
    """Create an unpredictable exclusive staging file inside an anchored parent."""
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
             | getattr(os, "O_CLOEXEC", 0))
    for _ in range(16):
        name = ".apatch-" + secrets.token_hex(12)
        try:
            return os.open(name, flags, 0o600, dir_fd=parent_fd), name
        except FileExistsError:
            continue
    raise Abort("Cannot allocate a unique ZIP staging file")


def _identity(parent_fd: int) -> tuple[int, int]:
    details = os.fstat(parent_fd)
    return details.st_dev, details.st_ino


def _cleanup_staged(root_fd: int, staged: list[tuple[str, str, tuple[int, int]]]) -> None:
    """Remove only temporary entries still under their original directory objects."""
    for relative, temp_name, identity in staged:
        try:
            with _parent_fd(root_fd, relative) as parent_fd:
                if _identity(parent_fd) == identity:
                    os.unlink(temp_name, dir_fd=parent_fd)
        except FileNotFoundError:
            continue
        except OSError:
            LOGGER.warning("ZIP staging cleanup needs inspection path=%s", relative)


def apply(config: Config, handoff: Handoff, root: Path, archive_data: Archive) -> None:
    path = patch_file(config, handoff)
    snapshot = path.read_bytes()
    if hashlib.sha256(snapshot).hexdigest() != archive_data.sha256:
        raise Abort("ZIP bytes changed after validation")
    current = inspect(config, handoff, root)
    if current.sha256 != archive_data.sha256 or current.changed != archive_data.changed:
        raise Abort("ZIP contents changed since the application preflight")
    _require_anchored_io()
    try:
        root_fd = os.open(root, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise Abort(f"Cannot anchor ZIP repository directory: {exc}") from exc
    staged: list[tuple[str, str, tuple[int, int]]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
            try:
                # Stage every member before replacing existing source files.
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    relative = info.filename.split("/", 1)[1]
                    if relative in RUNTIME_METADATA_MEMBERS:
                        continue
                    with _parent_fd(root_fd, relative, create=True) as parent_fd:
                        mode = _destination_mode(parent_fd, relative.rsplit("/", 1)[-1], relative)
                        descriptor, temp_name = _new_temp(parent_fd)
                        staged.append((relative, temp_name, _identity(parent_fd)))
                        with os.fdopen(descriptor, "wb") as out, archive.open(info) as source:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                out.write(chunk)
                            zip_mode = (info.external_attr >> 16) & 0o777
                            os.fchmod(out.fileno(), mode if mode is not None else
                                      (0o755 if zip_mode & 0o111 else 0o644))
                            out.flush()
                            os.fsync(out.fileno())
                for relative, temp_name, identity in staged:
                    with _parent_fd(root_fd, relative) as parent_fd:
                        if _identity(parent_fd) != identity:
                            raise Abort(f"ZIP destination directory changed during staging: {relative}")
                        basename = relative.rsplit("/", 1)[-1]
                        _destination_mode(parent_fd, basename, relative)
                        os.replace(temp_name, basename,
                                   src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                        LOGGER.info("patch file written path=%s", relative)
            except (OSError, zipfile.BadZipFile) as exc:
                raise Abort(f"Cannot stage or apply ZIP content: {exc}; inspect the applying checkpoint") from exc
            finally:
                _cleanup_staged(root_fd, staged)
        for relative in handoff.delete_paths:
            try:
                with _parent_fd(root_fd, relative) as parent_fd:
                    basename = relative.rsplit("/", 1)[-1]
                    if _destination_mode(parent_fd, basename, relative) is None:
                        raise Abort(f"ZIP deletion target disappeared: {relative}")
                    os.unlink(basename, dir_fd=parent_fd)
            except OSError as exc:
                raise Abort(f"Cannot safely delete ZIP path {relative}: {exc}") from exc
            LOGGER.info("patch file removed path=%s", relative)
    finally:
        os.close(root_fd)
