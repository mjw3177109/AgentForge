"""Synthetic Django acceptance fixture; NEVER use customer data or project secrets."""
from pathlib import Path


REQUEST = "Fix app/views.py add(a, b) so the existing Django business test passes."


def make_fixture(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "manage.py").write_text(
        "import os,sys\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE','demo.settings')\n"
        "from django.core.management import execute_from_command_line\n"
        "execute_from_command_line(sys.argv)\n", "utf-8"
    )
    demo = root / "demo"
    demo.mkdir()
    (demo / "__init__.py").write_text("", "utf-8")
    (demo / "settings.py").write_text(
        "SECRET_KEY = 'synthetic-fixture-never-deploy'\n"
        "INSTALLED_APPS = ['app']\n"
        "DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}\n"
        "ROOT_URLCONF = 'demo.urls'\n", "utf-8"
    )
    (demo / "urls.py").write_text("urlpatterns = []\n", "utf-8")
    app = root / "app"
    app.mkdir()
    (app / "__init__.py").write_text("", "utf-8")
    (app / "views.py").write_text(
        "def add(a, b):\n"
        "    return a - b\n",
        "utf-8"
    )
    (app / "tests.py").write_text(
        "from django.test import SimpleTestCase\n"
        "from .views import add\n"
        "class TestAddition(SimpleTestCase):\n"
        "    def test_business_addition(self):\n"
        "        self.assertEqual(add(3, 2), 5)\n", "utf-8"
    )
    return root


class ScriptedFakeAgent:
    """Used ONLY by offline CI; never classified as a REAL DeepSeek run."""
    def __init__(self, *, decision="APPROVE", path="app/views.py"):
        self.calls = 0
        self.decision = decision
        self.path = path

    def complete_model(self, system, user, schema):
        self.calls += 1
        if schema.__name__ == "CodingPlan":
            data = {
                "summary": "Fix arithmetic implementation only within the approved views module.",
                "files": [self.path],
                "acceptance": "The existing Django addition behavior test must pass independently."
            }
        elif schema.__name__ == "CodingProposal":
            data = {
                "summary": "Correct the integer addition routine without changing tests.",
                "edits": [{
                    "path": self.path,
                    "content": "def add(a, b):\n    return a + b\n",
                }],
            }
        else:
            data = {
                "decision": self.decision,
                "reason": "The candidate stays inside the approved module, with no config or test changes.",
            }
        return schema.model_validate(data)
