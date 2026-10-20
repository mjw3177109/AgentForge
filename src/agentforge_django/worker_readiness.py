"""Read-only V1.8 dedicated Worker startup gate.

Verifies local configuration, live PostgreSQL, applied migrations, and the
operator-approved Docker verifier content ID before a worker can accept tasks.
It does NOT attest that this process is on a separate physical VM.
"""
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from .docker_verify import docker_image, resolve_verifier_image
from .guard import BoundaryDenied


def worker_readiness(*, mode="dedicated"):
    if mode not in ("dedicated", "ci-staging"):
        raise ValueError("Unknown Worker preflight mode")
    checks = []

    def record(name, passed, code):
        checks.append({
            "check": name, "passed": passed is True,
            "failure_code": None if passed is True else code,
        })

    dedicated = mode == "dedicated"
    staging_allowed = (
        os.environ.get("CI", "").lower() == "true"
        and os.environ.get("AGENTFORGE_V07_STAGING_ENABLE") ==
            "GITHUB_ACTIONS_SYNTHETIC"
        and os.environ.get("DJANGO_SETTINGS_MODULE") ==
            "config.v07_staging_worker_settings"
    )
    record("execution_mode",
           (dedicated and os.getenv("AGENTFORGE_V07_PRODUCTION_WORKER_CONFIRM") ==
            "I_DEPLOY_IN_DEDICATED_VM" and
            os.getenv("DJANGO_SETTINGS_MODULE") == "config.v07_worker_settings")
           or (not dedicated and staging_allowed), "MODE_NOT_AUTHORIZED")
    record("dedicated_role",
           os.getenv("AGENTFORGE_WORKER_ROLE") == "trusted-dedicated"
           and bool(getattr(settings, "AGENTFORGE_V06_DEDICATED_WORKER", False))
           and bool(getattr(settings, "AGENTFORGE_V06_BOUNDED_REPAIR", False))
           and bool(getattr(settings, "AGENTFORGE_V05_ISOLATED_AUTONOMOUS", False)),
           "WORKER_ROLE_OR_PIPELINE_DISABLED")
    record("unsafe_execution_disabled",
           not getattr(settings, "AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS", True)
           and not getattr(settings, "AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY", True)
           and getattr(settings, "AGENTFORGE_VERIFICATION_BACKEND", None) == "docker"
           and not getattr(settings, "DEBUG", True),
           "UNSAFE_EXECUTION_CONFIGURATION")
    record("postgresql_with_heartbeat",
           connection.vendor == "postgresql"
           and getattr(settings, "AGENTFORGE_V09_HEARTBEAT_ENABLED", False) is True,
           "POSTGRESQL_HEARTBEAT_REQUIRED")

    default_db = settings.DATABASES.get("default", {})
    opts = default_db.get("OPTIONS", {})
    hostname = str(default_db.get("HOST", "")).lower()
    if dedicated:
        tls_ok = (
            default_db.get("ENGINE") == "django.db.backends.postgresql"
            and opts.get("sslmode") == "verify-full"
            and bool(opts.get("sslrootcert"))
            and hostname not in ("", "localhost", "127.0.0.1", "::1")
        )
    else:
        tls_ok = (
            staging_allowed and
            default_db.get("ENGINE") == "django.db.backends.postgresql"
            and opts.get("sslmode") == "disable"
            and hostname in ("localhost", "127.0.0.1")
        )
    record("postgres_transport", tls_ok, "POSTGRES_TRANSPORT_UNSAFE")

    roots = getattr(settings, "AGENTFORGE_ALLOWED_ROOTS", ())
    paths_ok = (
        isinstance(roots, (tuple, list)) and len(roots) > 0
        and all(isinstance(p, str) and Path(p).is_absolute()
                and Path(p).is_dir() and not Path(p).is_symlink()
                for p in roots)
    )
    record("project_roots", paths_ok, "APPROVED_PROJECT_ROOTS_INVALID")

    pin = getattr(settings, "AGENTFORGE_DOCKER_VERIFY_IMAGE_ID", None)
    record("pinned_verifier_config",
           getattr(settings, "AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN", False)
           is True and isinstance(pin, str)
           and len(pin) == 71 and pin.startswith("sha256:"),
           "APPROVED_VERIFIER_PIN_MISSING")

    # Fail before touching DB/Docker on any unsafe configuration. This ensures
    # zero model calls and no user repository/DB writes in rejected modes.
    can_probe = all(item["passed"] for item in checks)
    if can_probe:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                ready = cursor.fetchone() == (1,)
        except Exception:
            ready = False
        record("postgres_readonly_query", ready, "POSTGRES_QUERY_FAILED")
    else:
        record("postgres_readonly_query", False, "SKIPPED_INVALID_CONFIG")

    if can_probe and checks[-1]["passed"]:
        try:
            loader = MigrationExecutor(connection)
            pending = loader.migration_plan(loader.loader.graph.leaf_nodes("agentforge_django"))
            migrated = not pending
        except Exception:
            migrated = False
        record("schema_migrations_applied", migrated, "AGENTFORGE_SCHEMA_NOT_READY")
    else:
        record("schema_migrations_applied", False, "SKIPPED_INVALID_CONFIG_OR_DB")

    if all(item["passed"] for item in checks):
        if not shutil.which("docker"):
            resolved = False
        else:
            try:
                resolved = resolve_verifier_image(docker_image()) == pin
            except (BoundaryDenied, OSError, ValueError):
                resolved = False
        record("docker_verifier_identity", resolved, "DOCKER_PIN_UNAVAILABLE_OR_MISMATCH")
    else:
        record("docker_verifier_identity", False, "SKIPPED_INVALID_CONFIG_OR_SCHEMA")
    passed = all(item["passed"] for item in checks)
    return {
        "schema": "agentforge.django.v18.worker-preflight.v1",
        "mode": mode,
        "ready_to_accept_candidate_only_jobs": passed,
        "checks": checks,
        "checks_passed": sum(item["passed"] for item in checks),
        "checks_total": len(checks),
        "external_vm_independently_attested": False,
        "real_deepseek_tested": False,
        "production_release_authorized": False,
    }
