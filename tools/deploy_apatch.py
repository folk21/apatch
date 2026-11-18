#!/usr/bin/env python3
"""Deploy the committed apatch CLI independently of its development checkout.

Usage:
  python3 tools/deploy_apatch.py install [--source /path/to/apatch] [--smoke-only]
  python3 tools/deploy_apatch.py rollback
  python3 tools/deploy_apatch.py status

Run install from a cleanly merged main branch. The archive always uses committed
HEAD bytes, never changes the source checkout, and never runs Git publication.
No apatch process should be active during installation or rollback because the
installation-wide progress ledger must be copied consistently. The global
apatch.conf is stored once at the installation root and shared by releases.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import shlex
import subprocess
import sys
import tarfile
import tempfile


INSTALL_ROOT = Path.home() / ".local" / "opt" / "apatch"
CONFIG_FILE = INSTALL_ROOT / "apatch.conf"
MAX_CONFIG_BYTES = 65536
BIN_ROOT = Path.home() / ".local" / "bin"
MAX_SOURCE_BYTES = 256 * 1024 * 1024
COMMIT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


class DeployError(RuntimeError):
    """An operation cannot be completed without risking the active installation."""


def run(argv: list[str], *, cwd: Path | None = None, quiet: bool = False) -> str:
    result = subprocess.run(
        argv, cwd=cwd, text=True, stdout=subprocess.PIPE if quiet else None,
        stderr=subprocess.PIPE if quiet else None, check=False,
    )
    if result.returncode:
        detail = (result.stderr or "").strip() if quiet else "See command output above"
        raise DeployError(f"Command failed (exit {result.returncode}): {shlex.join(argv)}: {detail}")
    return result.stdout or ""


def git(source: Path, *args: str) -> str:
    return run(["git", "-C", str(source), *args], quiet=True).strip()


def real_directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise DeployError(f"Unsafe directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise DeployError(f"Directory became a symlink: {path}")


def find_source(value: str | None) -> tuple[Path, str]:
    candidate = Path(value or os.getcwd()).expanduser().resolve()
    root = Path(git(candidate, "rev-parse", "--show-toplevel")).resolve()
    if root == INSTALL_ROOT or INSTALL_ROOT in root.parents:
        raise DeployError("The source must be a development checkout, not an installed release")
    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != "main":
        raise DeployError(f"Install requires checked-out main, got {branch}")
    commit = git(root, "rev-parse", "--verify", "HEAD^{commit}")
    if not COMMIT_RE.fullmatch(commit):
        raise DeployError("Git returned an invalid commit object ID")
    upstream = git(root, "rev-parse", "--verify", "refs/remotes/origin/main")
    if commit != upstream:
        raise DeployError("main differs from the local origin/main ref; sync and verify before installing")
    status = git(root, "status", "--porcelain", "--untracked-files=normal")
    if status:
        print("WARNING: The source working tree is dirty; only committed HEAD is deployed.")
    return root, commit


def extract_archive(source: Path, commit: str, destination: Path) -> None:
    archive = subprocess.run(
        ["git", "-C", str(source), "archive", "--format=tar", commit],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if archive.returncode:
        raise DeployError(f"Cannot archive Git commit: {archive.stderr.decode(errors='replace').strip()}")
    if len(archive.stdout) > MAX_SOURCE_BYTES:
        raise DeployError("Git archive exceeds the deployment size limit")
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as stream:
        for member in stream:
            pure = PurePosixPath(member.name)
            if (not member.name or pure.is_absolute() or ".." in pure.parts
                    or not pure.parts or pure.parts[0] in {".", ".."}):
                raise DeployError(f"Unsafe Git archive path: {member.name!r}")
            target = destination.joinpath(*pure.parts)
            if member.isdir():
                real_directory(target)
                continue
            if not member.isfile() or member.size > MAX_SOURCE_BYTES - total:
                raise DeployError(f"Unsupported or oversized Git member: {member.name!r}")
            total += member.size
            real_directory(target.parent)
            if target.exists() or target.is_symlink():
                raise DeployError(f"Duplicate or unsafe archive member: {member.name!r}")
            source_file = stream.extractfile(member)
            if source_file is None:
                raise DeployError(f"Missing Git member contents: {member.name!r}")
            with target.open("xb") as output:
                shutil.copyfileobj(source_file, output)
            os.chmod(target, 0o755 if member.mode & 0o111 else 0o644)
    for required in ("apatch.py", "apatch.sh", "requirements.txt", "apatch.conf",
                     "apatch_lib/__init__.py", "run_tests.sh"):
        path = destination / required
        if not path.is_file() or path.is_symlink():
            raise DeployError(f"Required apatch source is missing: {required}")
    os.chmod(destination / "apatch.sh", 0o755)


def checked_release(link: Path) -> tuple[Path, str] | None:
    if not link.is_symlink():
        if link.exists():
            raise DeployError(f"Expected a release pointer, found another file: {link}")
        return None
    target = os.readlink(link)
    match = re.fullmatch(r"releases/([0-9a-f]{40}(?:[0-9a-f]{24})?)", target)
    if not match:
        raise DeployError(f"Unexpected release pointer: {link} -> {target}")
    release = INSTALL_ROOT / target
    if release.is_symlink() or not release.is_dir():
        raise DeployError(f"Referenced release is missing or unsafe: {release}")
    marker = release / "DEPLOY.json"
    if marker.is_symlink() or not marker.is_file():
        raise DeployError(f"Release marker is missing: {release}")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeployError(f"Cannot read release marker: {release}") from exc
    if data.get("commit") != match.group(1):
        raise DeployError(f"Release marker does not match its directory: {release}")
    return release, match.group(1)


def safe_config_bytes(path: Path) -> bytes:
    """Read an explicitly selected regular configuration, never a symlink."""
    if path.is_symlink() or not path.is_file():
        raise DeployError(f"Global configuration must be a regular file: {path}")
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise DeployError(f"Global configuration exceeds {MAX_CONFIG_BYTES} bytes: {path}")
    return path.read_bytes()


def preserve_config(candidate: Path, *, explicit: bool) -> None:
    """Create a stable configuration exactly once; never overwrite later edits."""
    if CONFIG_FILE.exists() or CONFIG_FILE.is_symlink():
        safe_config_bytes(CONFIG_FILE)
        if explicit:
            raise DeployError("--config is only supported for the first installation; "
                              f"edit the preserved configuration at {CONFIG_FILE} instead")
        return
    contents = safe_config_bytes(candidate)
    destination = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.new-{os.getpid()}")
    if destination.exists() or destination.is_symlink():
        raise DeployError(f"Temporary configuration already exists: {destination}")
    try:
        with destination.open("xb") as stream:
            stream.write(contents)
        destination.chmod(0o600)
        os.replace(destination, CONFIG_FILE)
    finally:
        if destination.exists():
            destination.unlink()


def link_config(release: Path) -> None:
    """Bind a release to installation-wide settings shared across upgrades and rollback."""
    safe_config_bytes(CONFIG_FILE)
    config = release / "apatch.conf"
    if config.is_symlink():
        if os.readlink(config) != "../../apatch.conf":
            raise DeployError(f"Unrecognized release configuration link: {config}")
        return
    if not config.is_file():
        raise DeployError(f"Release configuration is missing or unsafe: {config}")
    config.unlink()
    config.symlink_to("../../apatch.conf")


def copy_progress(source: Path | None, destination: Path) -> None:
    target = destination / ".apatch" / "progress"
    if target.is_symlink():
        raise DeployError("Unsafe destination progress directory")
    if target.exists():
        shutil.rmtree(target)
    if source is None or not source.exists():
        return
    if source.is_symlink() or not source.is_dir():
        raise DeployError(f"Unsafe source progress directory: {source}")
    for root, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            item = Path(root) / name
            if item.is_symlink() or (not item.is_dir() and not item.is_file()):
                raise DeployError(f"Unsupported progress artifact: {item}")
    real_directory(target.parent)
    shutil.copytree(source, target, symlinks=False)


def smoke(release: Path) -> None:
    run([str(release / "apatch.sh"), "--help"], cwd=release, quiet=True)
    run([str(release / "apatch.sh"), "info=PROGRESS"], cwd=release, quiet=True)


def atomic_link(link: Path, commit: str) -> None:
    temp = link.with_name(link.name + f".new-{os.getpid()}")
    if temp.exists() or temp.is_symlink():
        raise DeployError(f"Temporary pointer already exists: {temp}")
    try:
        temp.symlink_to(f"releases/{commit}")
        os.replace(temp, link)
    finally:
        if temp.is_symlink():
            temp.unlink()


def ensure_wrappers() -> None:
    real_directory(BIN_ROOT)
    path = INSTALL_ROOT / "current" / "apatch.sh"
    script = f"#!/bin/sh\nset -eu\nexec {shlex.quote(str(path))} \"$@\"\n"
    for name in ("apatch", "apatch.sh"):
        destination = BIN_ROOT / name
        if destination.is_symlink():
            raise DeployError(f"Wrapper is a symlink and will not be overwritten: {destination}")
        if destination.exists():
            if not destination.is_file():
                raise DeployError(f"Unsafe existing wrapper: {destination}")
            if destination.read_text(encoding="utf-8") != script:
                raise DeployError(f"Existing wrapper belongs to another installation: {destination}")
            continue
        candidate = destination.with_name(destination.name + f".new-{os.getpid()}")
        try:
            candidate.write_text(script, encoding="utf-8")
            candidate.chmod(0o755)
            os.replace(candidate, destination)
        finally:
            if candidate.exists():
                candidate.unlink()


def prepare_environment(release: Path, *, smoke_only: bool) -> None:
    print("Creating isolated Python environment and installing dependencies...")
    run([sys.executable, "-m", "venv", str(release / ".venv")])
    run([str(release / ".venv" / "bin" / "python"), "-m", "pip", "install", "-r",
         str(release / "requirements.txt")])
    print("Running installation smoke checks...")
    smoke(release)
    if not smoke_only:
        print("Running apatch's regular test suite before activation...")
        run(["sh", "./run_tests.sh"], cwd=release)


def install(source_arg: str | None, smoke_only: bool, config_arg: str | None = None) -> None:
    source, commit = find_source(source_arg)
    real_directory(INSTALL_ROOT)
    real_directory(INSTALL_ROOT / "releases")
    active = checked_release(INSTALL_ROOT / "current")
    checked_release(INSTALL_ROOT / "previous")
    release = INSTALL_ROOT / "releases" / commit
    if config_arg is not None and (CONFIG_FILE.exists() or CONFIG_FILE.is_symlink()):
        raise DeployError("--config is only supported for the first installation")
    if active is not None and active[1] == commit:
        ensure_wrappers()
        print(f"Already deployed: {commit}\nExecutable: {BIN_ROOT / 'apatch'}")
        return
    if release.is_symlink():
        raise DeployError(f"Unsafe existing release path: {release}")
    if release.exists():
        marker = release / "DEPLOY.json"
        if not marker.is_file() or json.loads(marker.read_text()).get("commit") != commit:
            raise DeployError(f"Unverified existing release: {release}")
        print(f"Reusing existing committed release: {commit}")
    else:
        stage = Path(tempfile.mkdtemp(prefix=".apatch-stage-", dir=INSTALL_ROOT / "releases"))
        try:
            print(f"Building release from {source} at {commit}...")
            extract_archive(source, commit, stage)
            prepare_environment(stage, smoke_only=smoke_only)
            (stage / "DEPLOY.json").write_text(json.dumps({
                "commit": commit,
                "source": str(source),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "checks": "smoke-only" if smoke_only else "regular-tests",
            }, indent=2) + "\n", encoding="utf-8")
            os.replace(stage, release)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    config_source = (Path(config_arg).expanduser() if config_arg is not None else
                     active[0] / "apatch.conf" if active is not None else
                     release / "apatch.conf")
    preserve_config(config_source, explicit=config_arg is not None)
    link_config(release)
    source_progress = (active[0] if active else source) / ".apatch" / "progress"
    copy_progress(source_progress, release)
    smoke(release)
    ensure_wrappers()
    if active is not None:
        atomic_link(INSTALL_ROOT / "previous", active[1])
    atomic_link(INSTALL_ROOT / "current", commit)
    print(f"Active release: {commit}\nExecutable: {BIN_ROOT / 'apatch'}")
    print("The development checkout was not modified. Keep it idle during deployment.")


def rollback() -> None:
    current = checked_release(INSTALL_ROOT / "current")
    previous = checked_release(INSTALL_ROOT / "previous")
    if current is None or previous is None:
        raise DeployError("Rollback requires both current and previous releases")
    if current[1] == previous[1]:
        raise DeployError("Current and previous releases are identical")
    copy_progress(current[0] / ".apatch" / "progress", previous[0])
    smoke(previous[0])
    ensure_wrappers()
    atomic_link(INSTALL_ROOT / "previous", current[1])
    atomic_link(INSTALL_ROOT / "current", previous[1])
    print(f"Rolled back to {previous[1]} (formerly {current[1]})")


def status() -> None:
    current = checked_release(INSTALL_ROOT / "current")
    previous = checked_release(INSTALL_ROOT / "previous")
    print(f"Installation: {INSTALL_ROOT}")
    print(f"Current: {current[1] if current else 'not installed'}")
    print(f"Previous: {previous[1] if previous else 'none'}")
    print(f"Launcher: {BIN_ROOT / 'apatch'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    deploy = commands.add_parser("install", help="Build and activate committed main")
    deploy.add_argument("--source", default=None, help="Development checkout (default: cwd)")
    deploy.add_argument("--config", default=None,
                        help="Optional existing apatch.conf to preserve on first installation")
    deploy.add_argument("--smoke-only", action="store_true",
                        help="Skip the normal test suite; keep help/progress checks")
    commands.add_parser("rollback", help="Activate the previous release")
    commands.add_parser("status", help="Show installed commit identities")
    args = parser.parse_args()
    try:
        if args.command == "install":
            install(args.source, args.smoke_only, args.config)
        elif args.command == "rollback":
            rollback()
        else:
            status()
    except (DeployError, OSError, ValueError) as exc:
        print(f"DEPLOY STOP: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
