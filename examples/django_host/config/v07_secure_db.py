"""Fail-closed external PostgreSQL with authenticated TLS, no SQLite fallback."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def external_database():
    required = (
        "AGENTFORGE_PG_HOST", "AGENTFORGE_PG_NAME", "AGENTFORGE_PG_USER",
        "AGENTFORGE_PG_PASSWORD", "AGENTFORGE_PG_SSLROOTCERT",
    )
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise ImproperlyConfigured("Missing PostgreSQL configuration: " + ", ".join(missing))
    host = os.environ["AGENTFORGE_PG_HOST"]
    if host in ("127.0.0.1", "localhost", "::1"):
        raise ImproperlyConfigured("Production Worker requires an external PostgreSQL host")
    if os.environ.get("AGENTFORGE_PG_SSLMODE") != "verify-full":
        raise ImproperlyConfigured("Remote PostgreSQL TLS must use verify-full")
    cert = Path(os.environ["AGENTFORGE_PG_SSLROOTCERT"]).expanduser()
    if not cert.is_file() or cert.is_symlink():
        raise ImproperlyConfigured("Trusted PostgreSQL CA certificate missing or unsafe")
    port = os.environ.get("AGENTFORGE_PG_PORT", "5432")
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ImproperlyConfigured("Invalid PostgreSQL port")
    return {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["AGENTFORGE_PG_NAME"],
        "USER": os.environ["AGENTFORGE_PG_USER"],
        "PASSWORD": os.environ["AGENTFORGE_PG_PASSWORD"],
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": 0,
        "OPTIONS": {
            "sslmode": "verify-full",
            "sslrootcert": str(cert.resolve(strict=True)),
            "connect_timeout": 10,
        },
    }}
