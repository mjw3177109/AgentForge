"""Linux V2.2 subreaper: detect children escaping the original process group.

A dedicated supervisor has exclusive ownership of its OS child processes.
pidfds avoid sending signals to recycled PIDs. This does NOT contain Docker
daemon processes, privileged escapes, external services or hostile kernels.
"""
import ctypes
import os
import signal
import sys
import time
from contextlib import contextmanager

PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37


def adopted_child_pids():
    """Read all direct children of all threads in this dedicated supervisor."""
    if sys.platform != "linux":
        raise RuntimeError("Linux subreaper required")
    children = set()
    for task in os.listdir("/proc/self/task"):
        if not task.isdigit():
            raise RuntimeError("Unexpected Linux task entry")
        try:
            with open(f"/proc/self/task/{task}/children", encoding="ascii") as stream:
                data = stream.read(16385)
        except FileNotFoundError:
            continue
        if len(data) > 16384:
            raise RuntimeError("Linux child inventory exceeds size bound")
        for part in data.split():
            if not part.isascii() or not part.isdecimal() or int(part) <= 1:
                raise RuntimeError("Malformed Linux child identifier")
            children.add(int(part))
    if len(children) > 64:
        raise RuntimeError("Linux child inventory exceeds count bound")
    return children


@contextmanager
def exclusive_subreaper():
    """Require a single-job Linux process and restore original prctl state."""
    if (sys.platform != "linux"
            or not callable(getattr(os, "pidfd_open", None))
            or not callable(getattr(signal, "pidfd_send_signal", None))):
        raise RuntimeError("Linux pidfd supervision unavailable")
    if adopted_child_pids():
        raise RuntimeError("Dedicated supervisor already owns child processes")
    libc = ctypes.CDLL(None, use_errno=True)
    existing = ctypes.c_int(0)
    if libc.prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(existing), 0, 0, 0) != 0:
        raise RuntimeError("Cannot inspect Linux child-subreaper mode")
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        raise RuntimeError("Cannot enable Linux child-subreaper mode")
    try:
        yield
    finally:
        if libc.prctl(PR_SET_CHILD_SUBREAPER, existing.value, 0, 0, 0) != 0:
            raise RuntimeError("Cannot restore Linux child-subreaper mode")


def _kill_adopted_child(pid):
    """Open a stable PID handle before signaling an adopted child."""
    try:
        fd = os.pidfd_open(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    try:
        # Recheck that the child is STILL ours before using the stable pidfd.
        if pid not in adopted_child_pids():
            return True
        try:
            signal.pidfd_send_signal(fd, signal.SIGKILL, None, 0)
        except ProcessLookupError:
            pass
        return True
    except (OSError, RuntimeError, ValueError):
        return False
    finally:
        os.close(fd)


def drain_adopted_children(*, seconds=5.0):
    """Return (quiet_confirmed, adopted_seen). Never signal unrelated PIDs.

    Call only while exclusive_subreaper() is active AND after the initial
    job leader has exited/been reaped. Found descendants always taint the
    job outcome even if they can subsequently be reaped.
    """
    if type(seconds) not in (int, float) or not 0 < seconds <= 15:
        return False, False
    deadline = time.monotonic() + seconds
    quiet_since = None
    observed = set()
    try:
        while time.monotonic() < deadline:
            children = adopted_child_pids()
            observed.update(children)
            if len(observed) > 64:
                return False, True
            if children:
                quiet_since = None
                for pid in children:
                    try:
                        os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        return False, True
                    if pid in adopted_child_pids() and not _kill_adopted_child(pid):
                        return False, True
            else:
                if quiet_since is None:
                    quiet_since = time.monotonic()
                if time.monotonic() - quiet_since >= 0.15:
                    return True, bool(observed)
            time.sleep(0.03)
    except (OSError, RuntimeError, ValueError):
        return False, bool(observed)
    return False, bool(observed)
