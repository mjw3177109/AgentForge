"""V2.1 bounded Linux process-group termination for a trusted Worker.

Fail closed if the process group is not quiescent. Linux /proc lets us
distinguish dead-but-unreaped zombie descendants from executable processes.
This cannot detect detached sessions or Docker daemon containers.
"""
import os
import signal
import sys
import time
import subprocess


def group_quiescent(pgid):
    if type(pgid) is not int or pgid <= 1:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    # A zombie can hold a process-group ID until init reaps it, but cannot
    # run code. Treat only fully readable /proc states as evidence.
    if sys.platform != "linux" or not os.path.isdir("/proc"):
        return False
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/stat", encoding="ascii") as fp:
                    raw = fp.read()
            except FileNotFoundError:
                continue  # PID vanished during inventory.
            # Name may contain parentheses, so split at the LAST ") ".
            fields = raw.rsplit(") ", 1)[1].split()
            if len(fields) < 3:
                return False
            if int(fields[2]) == pgid and fields[0] not in ("Z", "X", "x"):
                return False
        return True
    except (OSError, ValueError, IndexError):
        return False


def _send_group_signal(pgid, action):
    try:
        os.killpg(pgid, action)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        return False


def terminate_process_group(child, *, term_grace=5.0, kill_grace=5.0):
    """Always send a final KILL, even when leader exited after TERM.

    Used only for a child launched with start_new_session=True. A failed
    probe or un-reaped leader returns False. Never deletes DB leases or Docker
    containers; the caller must still mark this job as failed.
    """
    if not isinstance(term_grace, (int, float)) or not 0 < term_grace <= 30:
        return False
    if not isinstance(kill_grace, (int, float)) or not 0 < kill_grace <= 30:
        return False
    if type(child.pid) is not int or child.pid <= 1:
        return False
    pgid = child.pid
    term_ok = _send_group_signal(pgid, signal.SIGTERM)
    reaped = False
    try:
        child.wait(timeout=term_grace)
        reaped = True
    except subprocess.TimeoutExpired:
        pass
    except OSError:
        return False
    # A child can exit on TERM while a grandchild ignores it.
    kill_ok = _send_group_signal(pgid, signal.SIGKILL)
    if not reaped:
        try:
            child.wait(timeout=kill_grace)
            reaped = True
        except (subprocess.TimeoutExpired, OSError):
            return False
    deadline = time.monotonic() + kill_grace
    while time.monotonic() < deadline:
        if group_quiescent(pgid):
            return term_ok and kill_ok and reaped
        time.sleep(0.05)
    return term_ok and kill_ok and reaped and group_quiescent(pgid)
