#!/usr/bin/env python3
"""REAL Linux process-group timeout smoke: no Docker, no provider calls.

Two disposable Python fixtures:
1) direct child refuses SIGTERM;
2) direct child handles TERM and exits, grandchild refuses TERM.
They run in isolated OS process groups; all captured output is discarded.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from agentforge_django.v21_process_guard import (
    group_quiescent, terminate_process_group,
)


def _wait_marker(path):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            return
        time.sleep(0.03)
    raise RuntimeError("Synthetic process did not signal readiness")


def _run_case(folder, *, descendant):
    ready = Path(folder) / ("grandchild.pid" if descendant else "leader.ready")
    if descendant:
        # The grandchild stays in the original process group, ignoring TERM.
        # The leader intentionally exits on TERM; the escalation must still
        # SIGKILL that grandchild even though leader.wait() succeeds.
        code = """
import os,signal,subprocess,sys,time
signal.signal(signal.SIGTERM, lambda a,b: sys.exit(0))
script = 'import signal,time,os; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path(' + repr(sys.argv[1]) + ').write_text(str(os.getpid())); time.sleep(90)'
subprocess.Popen([sys.executable,'-c',script],
                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
while True: time.sleep(0.1)
"""
    else:
        code = """
import os,signal,sys,time
from pathlib import Path
signal.signal(signal.SIGTERM,signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
while True: time.sleep(0.1)
"""
    leader = subprocess.Popen(
        [sys.executable, "-c", code, str(ready)],
        start_new_session=True, shell=False,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_marker(ready)
        try:
            leader.wait(timeout=0.15)
            raise RuntimeError("Synthetic timeout did not occur")
        except subprocess.TimeoutExpired:
            pass
        cleaned = terminate_process_group(
            leader, term_grace=0.3, kill_grace=3.0
        )
        return cleaned and group_quiescent(leader.pid)
    finally:
        # This is a synthetic process group under our control only.
        if not group_quiescent(leader.pid):
            try:
                os.killpg(leader.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            leader.wait(timeout=3)
        except subprocess.TimeoutExpired:
            leader.kill()
            leader.wait(timeout=3)


def main():
    if sys.platform != "linux" or not os.path.isdir("/proc"):
        raise SystemExit("V2.1 real process-group smoke requires Linux /proc")
    with tempfile.TemporaryDirectory(prefix="af-v21-process-smoke-") as td:
        leader = _run_case(td, descendant=False)
        subtree = _run_case(td, descendant=True)
    report = {
        "gate": "V21_REAL_LINUX_PROCESS_GROUP_TERMINATION",
        "sigterm_resistant_leader_killed": leader,
        "leader_exits_on_term_but_stubborn_grandchild_killed": subtree,
        "external_vm_deployed": False,
        "docker_daemon_container_lifetime_attested": False,
        "real_deepseek_used": False,
        "production_release_authorized": False,
    }
    print(json.dumps(report, sort_keys=True))
    if not (leader and subtree):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
