"""Ephemeral one-shot worker using the same CI Postgres, not a web process."""
from .v06_worker_settings import *  # noqa: F403,F401
from .v07_staging_common import STAGING_DATABASES

DATABASES = STAGING_DATABASES
DEBUG = False
ALLOWED_HOSTS = []
AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS = False

# Real PostgreSQL background heartbeat in the separate CI worker process.
AGENTFORGE_V09_HEARTBEAT_ENABLED = True
AGENTFORGE_V09_HEARTBEAT_INTERVAL = 1

# CI-local image is approved by the ephemeral runner immediately after build.
# This is NOT a production image signature or external VM attestation.
import os
AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN = True
AGENTFORGE_DOCKER_VERIFY_IMAGE_ID = os.environ.get("AGENTFORGE_DOCKER_VERIFY_IMAGE_ID")
