#!/usr/bin/env python3
"""Real local Docker smoke test using a disposable minimal Django application."""
import json
import os
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")
import django
django.setup()

from agentforge_django.docker_verify import docker_verification


def main():
    with tempfile.TemporaryDirectory(prefix="agentforge-django-smoke-") as directory:
        root = Path(directory)
        (root / "manage.py").write_text(
            "import os,sys\n"
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE','sample.settings')\n"
            "from django.core.management import execute_from_command_line\n"
            "execute_from_command_line(sys.argv)\n",
            encoding="utf-8",
        )
        app = root / "sample"
        app.mkdir()
        (app / "__init__.py").write_text("", encoding="utf-8")
        (app / "settings.py").write_text(
            "SECRET_KEY = 'local-only-smoke-not-real'\n"
            "INSTALLED_APPS = ['sample']\n"
            "DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}\n"
            "ROOT_URLCONF = 'sample.urls'\n",
            encoding="utf-8",
        )
        (app / "urls.py").write_text("urlpatterns = []\n", encoding="utf-8")
        (app / "tests.py").write_text(
            "from django.test import SimpleTestCase\n"
            "class Behavior(SimpleTestCase):\n"
            "    def test_actual_business_assertion(self):\n"
            "        self.assertEqual(2+2, 4)\n",
            encoding="utf-8",
        )
        result = docker_verification(root)
        print(json.dumps({
            "backend": result["backend"], "passed": result["passed"],
            "checks": [{"success": item["success"],
                        "reason": item.get("reason", "")} for item in result["checks"]],
        }))
        if not result["passed"]:
            # This test fixture is synthetic and contains NO user code or secrets.
            # Show bounded Docker stderr for actionable CI diagnosis only.
            for item in result["checks"]:
                if not item["success"]:
                    print("SMOKE_DIAGNOSTIC", json.dumps({
                        "returncode": item.get("returncode"),
                        "stderr": item.get("stderr", "")[-2500:],
                        "stdout": item.get("stdout", "")[-500:],
                    }))
            raise SystemExit(2)


if __name__ == "__main__":
    main()
