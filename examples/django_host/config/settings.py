"""Development settings for the optional AgentForge host. Never deploy as-is."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-demo-only-change-before-deploy")
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "agentforge_django",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "dev.sqlite3",
}}
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# Explicit allowlist; NOTHING enabled by default.
AGENTFORGE_ALLOWED_ROOTS = [
    str(Path(value).expanduser().resolve()) for value in
    os.getenv("AGENTFORGE_ALLOWED_ROOTS", "").split(os.pathsep) if value.strip()
]
AGENTFORGE_ALLOW_AUTONOMOUS = False
AGENTFORGE_READONLY_LLM = False

# V0.4: every executable business test must run in an offline Docker sandbox.
AGENTFORGE_VERIFICATION_BACKEND = "docker"
AGENTFORGE_DOCKER_VERIFY_IMAGE = "agentforge-django-verify:0.4"
AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY = False
AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS = False

# V0.5 is a separately enabled candidate-only coding pipeline.
# Enable only inside a trusted dedicated worker with project-level human approval.
AGENTFORGE_V05_ISOLATED_AUTONOMOUS = False
AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER = False
AGENTFORGE_V05_ALLOWED_LLM_HOSTS = ("api.deepseek.com",)
