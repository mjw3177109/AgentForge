"""Separate control-plane settings; role allows approval but NOT code execution."""
import os
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403,F401
from .v07_secure_db import external_database

if os.getenv("AGENTFORGE_LLM_API_KEY"):
    raise ImproperlyConfigured("Never place DeepSeek credentials in the Django web app")
if len(os.environ.get("DJANGO_SECRET_KEY", "")) < 32:
    raise ImproperlyConfigured("Production control Django secret is too weak")
hosts = [x.strip() for x in os.environ.get("AGENTFORGE_WEB_ALLOWED_HOSTS", "").split(",") if x.strip()]
if not hosts:
    raise ImproperlyConfigured("Control plane requires explicit ALLOWED_HOSTS")
DATABASES = external_database()
DEBUG = False
ALLOWED_HOSTS = hosts
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
AGENTFORGE_ALLOW_AUTONOMOUS = True  # Only allows privileged creation/approval.
AGENTFORGE_V05_ISOLATED_AUTONOMOUS = False
AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER = False
AGENTFORGE_V06_BOUNDED_REPAIR = False
AGENTFORGE_V06_DEDICATED_WORKER = False
AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS = False
AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY = False
