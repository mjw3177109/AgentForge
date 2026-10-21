"""V1.8 startup preflight regression: no DB/Docker contact if role is wrong."""
import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from agentforge_django.worker_readiness import worker_readiness


IMAGE_ID = "sha256:" + "a" * 64


def test_settings(root):
    return SimpleNamespace(
        AGENTFORGE_V06_DEDICATED_WORKER=True,
        AGENTFORGE_V06_BOUNDED_REPAIR=True,
        AGENTFORGE_V05_ISOLATED_AUTONOMOUS=True,
        AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS=False,
        AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY=False,
        AGENTFORGE_VERIFICATION_BACKEND="docker",
        DEBUG=False,
        AGENTFORGE_V09_HEARTBEAT_ENABLED=True,
        AGENTFORGE_ALLOWED_ROOTS=[str(root)],
        AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN=True,
        AGENTFORGE_DOCKER_VERIFY_IMAGE_ID=IMAGE_ID,
        DATABASES={"default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": "127.0.0.1",
            "OPTIONS": {"sslmode": "disable"},
        }},
    )


class WorkerStartupPreflightTests(SimpleTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="af-v18-preflight-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.env = {
            "CI": "true",
            "AGENTFORGE_V07_STAGING_ENABLE": "GITHUB_ACTIONS_SYNTHETIC",
            "DJANGO_SETTINGS_MODULE": "config.v07_staging_worker_settings",
            "AGENTFORGE_WORKER_ROLE": "trusted-dedicated",
            "AGENTFORGE_LLM_API_KEY": "",
        }

    def happy(self, *, db_success=True, migrations_pending=False,
              pin=IMAGE_ID, settings_obj=None, orphans=None, prior_lease=False):
        settings_obj = settings_obj or test_settings(self.root)
        connection = MagicMock()
        connection.vendor = "postgresql"
        cursor = connection.cursor.return_value.__enter__.return_value
        if db_success:
            cursor.fetchone.return_value = (1,)
        else:
            connection.cursor.side_effect = RuntimeError("PRIVATE_DB_PASSWORD")
        executor = MagicMock()
        executor.loader.graph.leaf_nodes.return_value = [
            ("agentforge_django", "0005_heartbeat_capability"),
        ]
        executor.migration_plan.return_value = (
            [object()] if migrations_pending else []
        )
        with patch.dict(os.environ, self.env, clear=False), patch(
            "agentforge_django.worker_readiness.settings", settings_obj
        ), patch("agentforge_django.worker_readiness.connection", connection), patch(
            "agentforge_django.worker_readiness.MigrationExecutor",
            return_value=executor
        ), patch("agentforge_django.worker_readiness.shutil.which",
                 return_value="/usr/bin/docker"), patch(
            "agentforge_django.worker_readiness.docker_image",
            return_value="agentforge-django-verify:0.4"
        ), patch("agentforge_django.worker_readiness.resolve_verifier_image",
                 return_value=pin) as image, patch(
            "agentforge_django.worker_readiness.list_verifier_containers",
            return_value=[] if orphans is None else orphans,
        ), patch(
            "agentforge_django.worker_readiness.JobLease.objects.exists",
            return_value=prior_lease,
        ):
            result = worker_readiness(mode="ci-staging")
        return result, connection, executor, image

    def test_positive_ci_preflight_checks_real_contract_not_vm_attestation(self):
        result, connection, executor, image = self.happy()
        self.assertTrue(result["ready_to_accept_candidate_only_jobs"])
        self.assertEqual(result["checks_passed"], result["checks_total"])
        self.assertEqual(result["checks_total"], 13)
        self.assertFalse(result["external_vm_independently_attested"])
        self.assertFalse(result["real_deepseek_tested"])
        self.assertFalse(result["production_release_authorized"])
        connection.cursor.assert_called_once()
        executor.migration_plan.assert_called_once()
        image.assert_called_once()

    def test_fail_before_db_and_docker_if_worker_role_not_authorized(self):
        with patch.dict(os.environ, {
            **self.env, "AGENTFORGE_WORKER_ROLE": "web-user"
        }, clear=False), patch(
            "agentforge_django.worker_readiness.settings",
            test_settings(self.root)
        ), patch("agentforge_django.worker_readiness.connection") as conn, patch(
            "agentforge_django.worker_readiness.resolve_verifier_image"
        ) as image:
            conn.vendor = "postgresql"
            report = worker_readiness(mode="ci-staging")
        self.assertFalse(report["ready_to_accept_candidate_only_jobs"])
        conn.cursor.assert_not_called()
        image.assert_not_called()
        self.assertIn("WORKER_ROLE_OR_PIPELINE_DISABLED", [
            item["failure_code"] for item in report["checks"]
        ])

    def test_unavailable_postgres_never_triggers_image_or_task_execution(self):
        result, _, executor, image = self.happy(db_success=False)
        self.assertFalse(result["ready_to_accept_candidate_only_jobs"])
        self.assertIn("POSTGRES_QUERY_FAILED",
                      [c["failure_code"] for c in result["checks"]])
        self.assertNotIn("PRIVATE_DB_PASSWORD", json.dumps(result))
        executor.migration_plan.assert_not_called()
        image.assert_not_called()

    def test_unapplied_schema_blocks_worker(self):
        result, _, _, image = self.happy(migrations_pending=True)
        self.assertFalse(result["ready_to_accept_candidate_only_jobs"])
        self.assertIn("AGENTFORGE_SCHEMA_NOT_READY",
                      [c["failure_code"] for c in result["checks"]])
        image.assert_not_called()

    def test_docker_identity_mismatch_blocks_after_schema_check(self):
        result, _, _, image = self.happy(pin="sha256:" + "b" * 64)
        self.assertFalse(result["ready_to_accept_candidate_only_jobs"])
        status = {item["check"]: item for item in result["checks"]}
        self.assertEqual(
            status["docker_verifier_identity"]["failure_code"],
            "DOCKER_PIN_UNAVAILABLE_OR_MISMATCH",
        )
        self.assertEqual(
            status["orphan_verifier_containers"]["failure_code"],
            "SKIPPED_INVALID_CONFIG_OR_DOCKER",
        )
        image.assert_called_once()

    def test_no_actual_model_or_production_vm_claim(self):
        result, _, _, _ = self.happy()
        self.assertNotIn("model_cost", result)
        self.assertNotIn("API_KEY", json.dumps(result))
        self.assertFalse(result["external_vm_independently_attested"])

    def test_restart_with_existing_lease_denies_before_docker(self):
        result, connection, executor, image = self.happy(prior_lease=True)
        self.assertFalse(result["ready_to_accept_candidate_only_jobs"])
        gates = {x["check"]: x for x in result["checks"]}
        self.assertEqual(gates["no_prior_worker_leases"]["failure_code"],
                         "ACTIVE_OR_STALE_WORKER_LEASE_REQUIRES_OPERATOR")
        self.assertEqual(gates["docker_verifier_identity"]["failure_code"],
                         "SKIPPED_INVALID_CONFIG_OR_SCHEMA")
        image.assert_not_called()
        connection.cursor.assert_called_once()
        executor.migration_plan.assert_called_once()

    def test_orphan_verifier_container_refuses_new_worker_jobs(self):
        orphans = [{"container_id": "a" * 64,
                    "name": "agentforge-verify-" + "1" * 20}]
        result, connection, executor, image = self.happy(orphans=orphans)
        self.assertFalse(result["ready_to_accept_candidate_only_jobs"])
        self.assertEqual(result["checks"][-1]["check"],
                         "orphan_verifier_containers")
        self.assertEqual(result["checks"][-1]["failure_code"],
                         "VERIFIER_CONTAINERS_PRESENT_OR_UNKNOWN")
        connection.cursor.assert_called_once()
        executor.migration_plan.assert_called_once()
        image.assert_called_once()

    def test_management_command_is_fail_closed(self):
        with patch(
            "agentforge_django.management.commands.check_agentforge_worker.worker_readiness",
            return_value={
                "ready_to_accept_candidate_only_jobs": False,
                "checks": [{"check": "role", "passed": False,
                            "failure_code": "ROLE_BLOCKED"}],
                "checks_passed": 0, "checks_total": 1,
            }
        ):
            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command("check_agentforge_worker", "--mode", "ci-staging",
                             "--json", stdout=stdout)
            self.assertIn('"ready_to_accept_candidate_only_jobs": false',
                          stdout.getvalue())
