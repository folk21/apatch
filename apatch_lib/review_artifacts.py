"""Bounded, opt-in local evidence capture for independent reviewer commands."""

import hashlib
import json
import os
import secrets
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .gitutil import run
from .model import Abort


@dataclass(frozen=True)
class CapturedOutput:
    stdout: bytes
    exit_code: int
    timed_out: bool
    truncated: bool
    stdout_bytes: int
    stderr_bytes: int
    stdout_sha256: str
    stderr_sha256: str


def _kill_group(process):
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
    process.kill()


def _secure_file(path: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.fdopen(os.open(path, flags, 0o600), "wb")


def _atomic_json(path: Path, data: dict):
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with _secure_file(temporary) as stream:
            stream.write((json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ReviewArtifacts:
    """Capture one run under an ignored, private, non-symlinked runtime directory."""

    def __init__(self, root: Path, snapshot: tuple, max_output_bytes: int):
        parent = root / ".apatch" / "reviews"
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise Abort("REVIEW_ARTIFACT_UNSAFE: reviews path is not a normal directory")
        relative = ".apatch/reviews"
        tracked = run(["git", "ls-files", "--error-unmatch", "--", relative], root,
                      check=False)
        ignored = run(["git", "check-ignore", "--no-index", "--quiet", "--", relative],
                      root, check=False)
        if tracked.returncode != 1 or ignored.returncode != 0:
            raise Abort("REVIEW_ARTIFACT_UNSAFE: review storage must be untracked and ignored")
        try:
            parent.mkdir(mode=0o700, exist_ok=True)
            if parent.is_symlink():
                raise Abort("REVIEW_ARTIFACT_UNSAFE: reviews directory became a symlink")
            self.directory = parent / ("review-" + secrets.token_hex(12))
            self.directory.mkdir(mode=0o700)
        except OSError as exc:
            raise Abort(f"REVIEW_ARTIFACT_UNAVAILABLE: Cannot create private storage: {type(exc).__name__}") from exc
        self.max_output_bytes = max_output_bytes
        self.document = {
            "schema_version": 1,
            "review_id": self.directory.name,
            "snapshot": list(snapshot),
            "status": "STARTED",
            "providers": [],
        }
        self._persist()

    @property
    def relative_path(self):
        return self.directory.relative_to(self.directory.parents[2]).as_posix()

    def _persist(self):
        try:
            _atomic_json(self.directory / "manifest.json", self.document)
        except OSError as exc:
            raise Abort(f"REVIEW_ARTIFACT_UNAVAILABLE: Cannot persist manifest: {type(exc).__name__}") from exc

    def finish(self, status: str):
        self.document["status"] = status
        self._persist()

    def capture(self, provider, argv, cwd, env, payload: bytes, timeout: int) -> CapturedOutput:
        """Drain both pipes concurrently and stop the process on a bounded-output breach."""
        identifier = provider.id
        stdout_path = self.directory / (identifier + ".stdout")
        stderr_path = self.directory / (identifier + ".stderr")
        total = [0]
        counts = {"stdout": 0, "stderr": 0}
        digests = {"stdout": hashlib.sha256(), "stderr": hashlib.sha256()}
        preview = bytearray()
        guard = threading.Lock()
        exceeded = threading.Event()
        failed = threading.Event()

        def reader(pipe, output, name):
            try:
                with output:
                    while True:
                        chunk = pipe.read(65536)
                        if not chunk:
                            break
                        with guard:
                            available = max(0, self.max_output_bytes - total[0])
                            portion = chunk[:available]
                            total[0] += len(portion)
                            if len(portion) < len(chunk):
                                exceeded.set()
                        if portion:
                            output.write(portion)
                            digests[name].update(portion)
                            counts[name] += len(portion)
                            if name == "stdout" and len(preview) < 262145:
                                preview.extend(portion[:262145 - len(preview)])
            except OSError:
                failed.set()
            finally:
                pipe.close()

        def writer(pipe):
            try:
                with pipe:
                    pipe.write(payload)
                    pipe.flush()
            except (BrokenPipeError, OSError):
                pass

        try:
            stdout_file = _secure_file(stdout_path)
            stderr_file = _secure_file(stderr_path)
        except OSError as exc:
            raise Abort(f"REVIEW_ARTIFACT_UNAVAILABLE: Cannot open output files: {type(exc).__name__}") from exc
        try:
            with subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  start_new_session=True) as process:
                threads = [
                    threading.Thread(target=reader, args=(process.stdout, stdout_file, "stdout"), daemon=True),
                    threading.Thread(target=reader, args=(process.stderr, stderr_file, "stderr"), daemon=True),
                    threading.Thread(target=writer, args=(process.stdin,), daemon=True),
                ]
                for thread in threads:
                    thread.start()
                deadline = time.monotonic() + timeout
                timed_out = False
                while process.poll() is None:
                    if exceeded.is_set() or failed.is_set():
                        _kill_group(process)
                        break
                    if time.monotonic() >= deadline:
                        timed_out = True
                        _kill_group(process)
                        break
                    try:
                        process.wait(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
                    except subprocess.TimeoutExpired:
                        pass
                process.wait()
                for thread in threads:
                    thread.join(timeout=2)
                incomplete = any(thread.is_alive() for thread in threads)
                result = CapturedOutput(bytes(preview), process.returncode, timed_out,
                                        exceeded.is_set(), counts["stdout"], counts["stderr"],
                                        digests["stdout"].hexdigest(),
                                        digests["stderr"].hexdigest())
        except OSError as exc:
            stdout_file.close()
            stderr_file.close()
            raise Abort(f"REVIEW_UNAVAILABLE: Cannot run {identifier}: {type(exc).__name__}") from exc
        self.document["providers"].append({
            "id": identifier,
            "kind": provider.kind,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "truncated": result.truncated,
            "stdout_file": stdout_path.name,
            "stderr_file": stderr_path.name,
            "stdout_bytes": result.stdout_bytes,
            "stderr_bytes": result.stderr_bytes,
            "stdout_sha256": result.stdout_sha256,
            "stderr_sha256": result.stderr_sha256,
        })
        self._persist()
        if failed.is_set() or incomplete:
            raise Abort(f"REVIEW_ARTIFACT_UNAVAILABLE: Cannot safely capture {identifier} output")
        return result
