"""Remote PostgreSQL cannot silently degrade to SQLite or cleartext DB."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
import importlib.util

FILE = Path(__file__).resolve().parents[1] / "examples/django_host/config/v07_secure_db.py"
SPEC = importlib.util.spec_from_file_location("v07_secure_db_test_module", FILE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
external_database = MODULE.external_database


class ExternalPostgresContractTests(SimpleTestCase):
    def test_production_requires_verified_tls_and_external_host(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ca = Path(tmp.name) / "test-ca.pem"
        ca.write_text("test-only", encoding="utf-8")
        base = {
            "AGENTFORGE_PG_HOST": "pg.example.internal",
            "AGENTFORGE_PG_NAME": "example",
            "AGENTFORGE_PG_USER": "example",
            "AGENTFORGE_PG_PASSWORD": "fake-placeholder",
            "AGENTFORGE_PG_SSLROOTCERT": str(ca),
            "AGENTFORGE_PG_SSLMODE": "verify-full",
        }
        with patch.dict(os.environ, base):
            config = external_database()["default"]
        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["OPTIONS"]["sslmode"], "verify-full")
        self.assertEqual(config["HOST"], "pg.example.internal")
        for edits in [
            {"AGENTFORGE_PG_SSLMODE": "disable"},
            {"AGENTFORGE_PG_HOST": "127.0.0.1"},
            {"AGENTFORGE_PG_SSLROOTCERT": "/does-not-exist.pem"},
            {"AGENTFORGE_PG_PORT": "-2"},
        ]:
            with self.subTest(edits=edits), patch.dict(os.environ, {**base, **edits}):
                with self.assertRaises(ImproperlyConfigured):
                    external_database()
