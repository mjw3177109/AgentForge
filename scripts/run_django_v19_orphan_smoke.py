#!/usr/bin/env python3
"""V1.9 real Docker orphan visibility test. No model and no user project."""
import json
import os
import re
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")
import django
django.setup()
from agentforge_django.docker_verify import list_verifier_containers


def main():
    prefix = "agentforge-verify-"
    name = prefix + uuid.uuid4().hex[:20]
    before = list_verifier_containers()
    if before:
        raise SystemExit("Pre-existing verifier containers require operator inspection")
    try:
        # Docker CREATE only; nothing executes. A stopped container exercises
        # the exact label inventory also used by the dedicated Worker gate.
        created = subprocess.run(
            ["docker", "create", "--name", name, "--pull", "never",
             "--label", "org.agentforge.verifier=django-offline",
             "--network", "none", "agentforge-django-verify:0.4",
             "python", "-c", "pass"],
            capture_output=True, text=True, timeout=25, check=True,
        )
        during = list_verifier_containers()
        matched = [x for x in during if x["name"] == name]
        identified = len(matched) == 1 and re.fullmatch(
            r"[a-f0-9]{12,64}", matched[0]["container_id"]
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name], capture_output=True,
            timeout=20, check=False,
        )
    after = list_verifier_containers()
    evidence = {
        "gate": "V19_REAL_DOCKER_ORPHAN_INVENTORY",
        "initially_clear": len(before) == 0,
        "stopped_labelled_container_detected": bool(identified),
        "after_explicit_cleanup_clear": len(after) == 0,
        "no_paid_model_calls": True,
        "production_release_authorized": False,
        "independent_persistent_vm_deployed": False,
    }
    print(json.dumps(evidence, sort_keys=True))
    if not all((
        evidence["initially_clear"],
        evidence["stopped_labelled_container_detected"],
        evidence["after_explicit_cleanup_clear"],
    )):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
