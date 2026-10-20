"""Dedicated VM Worker: never serve Django HTTP using this module."""
import os
import re
from django.core.exceptions import ImproperlyConfigured
from .v06_worker_settings import *  # noqa: F403,F401
from .v07_secure_db import external_database

if os.getenv("AGENTFORGE_V07_PRODUCTION_WORKER_CONFIRM") != "I_DEPLOY_IN_DEDICATED_VM":
    raise ImproperlyConfigured("Worker requires dedicated-VM deployment confirmation")
if len(os.environ.get("DJANGO_SECRET_KEY", "")) < 32:
    raise ImproperlyConfigured("Production Worker Django secret is too weak")
DATABASES = external_database()
# Approved by the VM operator after building/verifying the exact local image.
# Container runs use the resolved immutable sha256 ID (never a mutable tag).
AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN = True
AGENTFORGE_DOCKER_VERIFY_IMAGE_ID = os.environ.get(
    "AGENTFORGE_DOCKER_VERIFY_IMAGE_ID", ""
)
if not re.fullmatch(r"sha256:[0-9a-f]{64}", AGENTFORGE_DOCKER_VERIFY_IMAGE_ID):
    raise ImproperlyConfigured(
        "Dedicated Worker requires operator-approved verifier Docker image ID"
    )
DEBUG = False
ALLOWED_HOSTS = []
AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY = False
AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS = False

# Durable PostgreSQL lease liveness; never automatically reclaim a lease.
AGENTFORGE_V09_HEARTBEAT_ENABLED = True
AGENTFORGE_V09_HEARTBEAT_INTERVAL = 10
