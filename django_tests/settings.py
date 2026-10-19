SECRET_KEY = "test-only-not-for-production"
DEBUG = False
USE_TZ = True
ROOT_URLCONF = "django_tests.urls"
ALLOWED_HOSTS = ["testserver"]
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "agentforge_django",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "django.template.context_processors.request",
    ]},
}]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
AGENTFORGE_ALLOWED_ROOTS = []
AGENTFORGE_ALLOW_AUTONOMOUS = False

AGENTFORGE_VERIFICATION_BACKEND = "docker"
AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY = False
AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS = False
