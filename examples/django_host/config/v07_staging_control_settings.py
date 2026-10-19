"""Ephemeral control process: no model key and no worker-role permission."""
from .settings import *  # noqa: F403,F401
from .v07_staging_common import STAGING_DATABASES

DATABASES = STAGING_DATABASES
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
AGENTFORGE_ALLOW_AUTONOMOUS = True  # Human approval only; not job execution.
AGENTFORGE_V05_ISOLATED_AUTONOMOUS = False
AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER = False
AGENTFORGE_V06_BOUNDED_REPAIR = False
AGENTFORGE_V06_DEDICATED_WORKER = False
AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS = False
