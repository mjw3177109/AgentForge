"""Ephemeral CI-only PostgreSQL setup; refuses any non-loopback DB endpoint.

This is not a reusable production settings module. It exists to prove a
cross-process Django control/worker handoff on an ephemeral GitHub runner.
"""
import os

from django.core.exceptions import ImproperlyConfigured

if not (
    os.environ.get("CI", "").lower() == "true"
    and os.environ.get("AGENTFORGE_V07_STAGING_ENABLE") == "GITHUB_ACTIONS_SYNTHETIC"
):
    raise ImproperlyConfigured("V0.7 PostgreSQL staging is CI-only")
if os.environ.get("AGENTFORGE_PG_HOST", "") not in ("127.0.0.1", "localhost"):
    raise ImproperlyConfigured("CI staging PostgreSQL must use loopback host")
for required in ("AGENTFORGE_PG_NAME", "AGENTFORGE_PG_USER", "AGENTFORGE_PG_PASSWORD",
                 "DJANGO_SECRET_KEY"):
    if not os.environ.get(required):
        raise ImproperlyConfigured(f"Missing CI staging setting: {required}")

STAGING_DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["AGENTFORGE_PG_NAME"],
        "USER": os.environ["AGENTFORGE_PG_USER"],
        "PASSWORD": os.environ["AGENTFORGE_PG_PASSWORD"],
        "HOST": os.environ["AGENTFORGE_PG_HOST"],
        "PORT": os.environ.get("AGENTFORGE_PG_PORT", "5432"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"sslmode": "disable"},
    }
}
