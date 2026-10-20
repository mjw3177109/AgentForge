#!/usr/bin/env python3
"""V1.7 real Docker pinned-image smoke (NO LLM, no customer files)."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")
import django
django.setup()

from django.test import override_settings
from agentforge_django.docker_verify import docker_verification
from agentforge_django.guard import BoundaryDenied
from agentforge_django.v05_fixture import make_fixture


def main():
    inspected = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}",
         "agentforge-django-verify:0.4"],
        check=True, capture_output=True, text=True, timeout=15,
    )
    approved_id = inspected.stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", approved_id):
        raise SystemExit("Docker returned an invalid image identity")
    with tempfile.TemporaryDirectory(prefix="af-v17-identity-smoke-") as folder:
        root = make_fixture(Path(folder) / "sample")
        (root / "app" / "views.py").write_text(
            "def add(a, b):\n    return a + b\n", "utf-8"
        )
        with override_settings(
            AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN=True,
            AGENTFORGE_DOCKER_VERIFY_IMAGE_ID=approved_id,
        ):
            verified = docker_verification(root)
        wrong_id = "sha256:" + ("b" if approved_id[7] != "b" else "a") * 64
        denied = False
        with override_settings(
            AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN=True,
            AGENTFORGE_DOCKER_VERIFY_IMAGE_ID=wrong_id,
        ):
            try:
                docker_verification(root)
            except BoundaryDenied:
                denied = True
        evidence = {
            "gate": "V17_REAL_DOCKER_CONTENT_IMAGE_ID",
            "pinned_docker_business_tests_passed": verified.get("passed") is True,
            "actual_verifier_image_id": approved_id,
            "reported_verifier_image_id_matches": verified.get("verifier_image_id") == approved_id,
            "wrong_pin_rejected": denied,
            "business_tests_executed": verified.get("business_tests_executed") is True,
            "real_deepseek_tested": False,
            "persistent_worker_vm_deployed": False,
            "production_release_authorized": False,
        }
        print(json.dumps(evidence, sort_keys=True))
        if not (
            evidence["pinned_docker_business_tests_passed"]
            and evidence["reported_verifier_image_id_matches"]
            and evidence["wrong_pin_rejected"]
            and evidence["business_tests_executed"]
        ):
            raise SystemExit(2)


if __name__ == "__main__":
    main()
