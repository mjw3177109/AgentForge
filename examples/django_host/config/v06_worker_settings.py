"""Dedicated V0.6 worker only; NEVER use this module for Django runserver.

A Django settings flag and a role marker are operator mistakes prevention,
NOT an OS security boundary. Run on separate trusted machine/VM with Docker.
"""
import os
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403

if os.getenv("AGENTFORGE_V06_ENABLE_WORKER") != "I_ACCEPT_DEDICATED_WORKER":
    raise ImproperlyConfigured("V0.6 worker requires explicit operator opt-in")
if os.getenv("AGENTFORGE_WORKER_ROLE") != "trusted-dedicated":
    raise ImproperlyConfigured("V0.6 worker must use trusted-dedicated role")
if not os.getenv("DJANGO_SECRET_KEY"):
    raise ImproperlyConfigured("Never use demo Django SECRET_KEY in worker")
if not AGENTFORGE_ALLOWED_ROOTS:
    raise ImproperlyConfigured("Worker must configure explicit allowlisted roots")

DEBUG = False
ALLOWED_HOSTS = []
AGENTFORGE_ALLOW_AUTONOMOUS = True
AGENTFORGE_V05_ISOLATED_AUTONOMOUS = True
AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER = True
AGENTFORGE_V06_BOUNDED_REPAIR = True
AGENTFORGE_V06_DEDICATED_WORKER = True
AGENTFORGE_VERIFICATION_BACKEND = "docker"
AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY = False
AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS = False
