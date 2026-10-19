#!/usr/bin/env python3
"""V1.6 actual Docker adversarial smoke: test-file writes fail closed.

Uses only a disposable synthetic Django app; no real model, user project or
network. The malicious fixture attempts write-to-tests during Django check.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")
import django
django.setup()

from agentforge_django.docker_verify import docker_verification
from agentforge_django.v05_fixture import make_fixture


def main():
    with tempfile.TemporaryDirectory(prefix="af-v16-malicious-django-") as folder:
        root = make_fixture(Path(folder) / "source")
        original_tests = (root / "app/tests.py").read_bytes()
        # A benign fixture must continue to pass in the read-only verifier.
        (root / "app/views.py").write_text(
            "def add(a, b):\n    return a + b\n", "utf-8"
        )
        safe = docker_verification(root)
        if not (
            safe["passed"] is True
            and safe["business_tests_executed"] is True
            and len(safe["checks"]) == 2
        ):
            raise SystemExit("Read-only verifier rejected the benign fixture")
        # Simulate an untrusted project trying to rewrite its own business
        # tests during the 'check' phase before Docker runs 'test'.
        manage = root / "manage.py"
        original_manage = manage.read_text("utf-8")
        poisoned = (
            "import sys\nfrom pathlib import Path\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'check':\n"
            "    Path('app/tests.py').write_text(\"from django.test import SimpleTestCase\\nclass Forged(SimpleTestCase):\\n    def test_fake(self): self.assertTrue(True)\\n\")\n"
            + original_manage
        )
        manage.write_text(poisoned, "utf-8")
        blocked = docker_verification(root)
        untouched = (root / "app/tests.py").read_bytes() == original_tests
        evidence = {
            "gate": "V16_REAL_DOCKER_READONLY_VERIFIER",
            "benign_fixture_passed": safe["passed"] is True,
            "malicious_write_attempt_rejected": blocked["passed"] is False,
            "malicious_django_check_failed": (
                bool(blocked["checks"])
                and blocked["checks"][0]["success"] is False
            ),
            "business_test_not_executed_after_attack": len(blocked["checks"]) == 1,
            "original_fixture_tests_unchanged": untouched,
            "real_deepseek_tested": False,
            "production_release_authorized": False,
        }
        print(json.dumps(evidence, sort_keys=True))
        if not all((
            evidence["benign_fixture_passed"],
            evidence["malicious_write_attempt_rejected"],
            evidence["malicious_django_check_failed"],
            evidence["business_test_not_executed_after_attack"],
            evidence["original_fixture_tests_unchanged"],
        )):
            raise SystemExit(2)


if __name__ == "__main__":
    main()
