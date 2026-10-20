#!/usr/bin/env python3
"""V2.2 real Linux setsid-escape tests, using synthetic Python only.

Runs in a one-off GitHub runner. Does not touch repositories, Docker,
PostgreSQL, models or external LLM services.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agentforge_django.v21_process_guard import group_quiescent, terminate_process_group
from agentforge_django.v22_subreaper import (
    exclusive_subreaper, drain_adopted_children,
)


def wait_for(path):
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            return
        time.sleep(0.02)
    raise RuntimeError("Synthetic child did not start")


def scenario(folder, *, parent_times_out):
    marker = Path(folder) / (
        "timeout-grandchild.pid" if parent_times_out else "exit-grandchild.pid"
    )
    # The grandchild creates its OWN session, deliberately escaping the
    # group of its direct parent, and refuses SIGTERM.
    descendant = """
import os,signal,sys,time
from pathlib import Path
os.setsid()
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
while True: time.sleep(.2)
"""
    leader = """
import os,subprocess,sys,time
from pathlib import Path
subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic()+5.0
while not Path(sys.argv[1]).exists() and time.monotonic()<deadline:
    time.sleep(.01)
if sys.argv[3] == 'exit':
    sys.exit(0)
while True: time.sleep(.2)
"""
    with exclusive_subreaper():
        child = subprocess.Popen(
            [sys.executable, "-c", leader, str(marker), descendant,
             "timeout" if parent_times_out else "exit"],
            start_new_session=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )
        group_finished = True
        try:
            wait_for(marker)
            if parent_times_out:
                try:
                    child.wait(timeout=.2)
                    raise RuntimeError("Synthetic parent unexpectedly exited")
                except subprocess.TimeoutExpired:
                    group_finished = terminate_process_group(
                        child, term_grace=.3, kill_grace=2
                    )
            else:
                child.wait(timeout=4)
            clean, found = drain_adopted_children(seconds=4)
            return {
                "escaped_descendant_observed": found,
                "escaped_descendant_terminated": clean,
                "original_group_quiescent": (
                    group_finished and group_quiescent(child.pid)
                ),
            }
        finally:
            # In failure cases, clean up ONLY this uniquely-created group and
            # adopted synthetic descendants; never select arbitrary processes.
            if child.poll() is None or not group_quiescent(child.pid):
                terminate_process_group(child, term_grace=.1, kill_grace=2)
            drain_adopted_children(seconds=3)


def main():
    if sys.platform != "linux" or not os.path.isdir("/proc"):
        raise SystemExit("This test requires a Linux /proc namespace")
    with tempfile.TemporaryDirectory(prefix="af-v22-escape-") as td:
        parent_normal = scenario(td, parent_times_out=False)
        parent_timeout = scenario(td, parent_times_out=True)
    report = {
        "schema": "agentforge.django.v22.real-linux-setsid-escape.v1",
        "leader_exits_normally_but_escaped_child_detected":
            all(parent_normal.values()),
        "leader_times_out_and_escaped_child_detected":
            all(parent_timeout.values()),
        "synthetic_only": True,
        "independent_vm_deployed": False,
        "real_deepseek_called": False,
        "production_release_authorized": False,
    }
    print(json.dumps(report, sort_keys=True))
    if not (report["leader_exits_normally_but_escaped_child_detected"]
            and report["leader_times_out_and_escaped_child_detected"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
