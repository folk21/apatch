"""Best-effort termination for subprocesses owned by the test harness."""

import os
import signal
import subprocess


def terminate_test_process(process: subprocess.Popen) -> None:
    """Terminate the process group, or its child when group signaling is denied."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except (PermissionError, ProcessLookupError):
            # A rejected group signal must not bypass direct-child cleanup.
            pass
    try:
        process.kill()
    except ProcessLookupError:
        # The process has already exited between timeout detection and cleanup.
        pass
