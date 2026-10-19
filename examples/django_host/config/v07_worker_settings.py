"""Dedicated VM Worker: never serve Django HTTP using this module."""
import os
from django.core.exceptions import ImproperlyConfigured
from .v06_worker_settings import *  # noqa: F403,F401
from .v07_secure_db import external_database

if os.getenv("AGENTFORGE_V07_PRODUCTION_WORKER_CONFIRM") != "I_DEPLOY_IN_DEDICATED_VM":
    raise ImproperlyConfigured("Worker requires dedicated-VM deployment confirmation")
if len(os.environ.get("DJANGO_SECRET_KEY", "")) < 32:
    raise ImproperlyConfigured("Production Worker Django secret is too weak")
DATABASES = external_database()
DEBUG = False
ALLOWED_HOSTS = []
AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY = False
AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS = False

# Durable PostgreSQL lease liveness; never automatically reclaim a lease.
AGENTFORGE_V09_HEARTBEAT_ENABLED = True
AGENTFORGE_V09_HEARTBEAT_INTERVAL = 10
