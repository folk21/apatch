"""Stage and apply already inspected ZIP bytes without owning workflow state."""

import hashlib
import io
import logging
import os
import stat
import tempfile
import zipfile
from pathlib import Path

from ..configuration.models import Config
from ..core.api import Abort
from ..core.paths import RUNTIME_METADATA_MEMBERS
from .inspection import inspect, patch_file
from .models import Archive, Handoff

LOGGER = logging.getLogger("apatch.patch")

def apply(config: Config, handoff: Handoff, root: Path, archive_data: Archive) -> None:
    path = patch_file(config, handoff)
    snapshot = path.read_bytes()
    if hashlib.sha256(snapshot).hexdigest() != archive_data.sha256:
        raise Abort("ZIP bytes changed after validation")
    # Repeat filesystem checks immediately before extraction to catch changed parents.
    current = inspect(config, handoff, root)
    if current.sha256 != archive_data.sha256 or current.changed != archive_data.changed:
        raise Abort("ZIP contents changed since the application preflight")
    staged = []
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        try:
            # Prepare all file bytes before replacing any existing destination.
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative = info.filename.split("/", 1)[1]
                if relative in RUNTIME_METADATA_MEMBERS:
                    continue
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                existing_mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else None
                descriptor, temp_name = tempfile.mkstemp(dir=destination.parent, prefix=".apatch-")
                staged.append((temp_name, destination, relative))
                with os.fdopen(descriptor, "wb") as out, archive.open(info) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                zip_mode = (info.external_attr >> 16) & 0o777
                os.chmod(temp_name, existing_mode if existing_mode is not None else (0o755 if zip_mode & 0o111 else 0o644))
            for temp_name, destination, relative in staged:
                os.replace(temp_name, destination)
                LOGGER.info("patch file written path=%s", relative)
        except OSError as exc:
            raise Abort(f"Cannot stage or apply ZIP content: {exc}; inspect the applying checkpoint") from exc
        finally:
            for temp_name, _, _ in staged:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
    for relative in handoff.delete_paths:
        (root / relative).unlink()
        LOGGER.info("patch file removed path=%s", relative)

