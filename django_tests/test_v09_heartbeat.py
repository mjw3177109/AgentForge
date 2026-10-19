"""No heartbeat threads spawned against SQLite; test heartbeat fencing/observability."""
from datetime import timedelta
from unittest.mock import patch
import uuid

from django.test import TestCase, override_settings
from django.utils import timezone

from agentforge_django.guard import BoundaryDenied
from agentforge_django.lease_diagnostics import lease_diagnostics
from agentforge_django.lease_heartbeat import LeaseHeartbeat, lease_owned
from agentforge_django.models import AgentJob, JobLease, ManagedProject


class HeartbeatContractTests(TestCase):
    def setUp(self):
        self.project = ManagedProject.objects.create(
            name="v09-project", root_path="/tmp/fixture-not-executed"
        )
        self.job = AgentJob.objects.create(
            project=self.project, status=AgentJob.Status.RUNNING,
        )
        self.lease = JobLease.objects.create(project=self.project, job=self.job)

    def test_operator_recovery_blocks_late_success_and_worker_audit(self):
        import tempfile
        from pathlib import Path
        from agentforge_django.runner import run_job
        from agentforge_django.recovery import recover_stopped_worker
        from agentforge_django.v05_fixture import make_fixture
        from agentforge_django.audit import verify_chain

        with tempfile.TemporaryDirectory(prefix="af-v10-recovery-") as folder:
            root = make_fixture(Path(folder) / "django")
            self.project.root_path = str(root)
            self.project.enabled = True
            self.project.save(update_fields=["root_path", "enabled"])
            job = AgentJob.objects.create(
                project=self.project, mode=AgentJob.Mode.VERIFY,
                status=AgentJob.Status.PENDING,
            )
            self.lease.delete()

            def simulate_verification_with_interrupted_worker(*args, **kwargs):
                # Emulates another administrator fencing this worker while
                # its independent verifier is busy; no real task gets deployed.
                recover_stopped_worker(job.pk, operator_confirmed=True)
                return {
                    "backend": "docker-offline", "passed": True,
                    "business_tests_executed": True,
                    "checks": [{"success": True}, {"success": True}],
                }

            with override_settings(
                AGENTFORGE_ALLOWED_ROOTS=[str(root)],
                AGENTFORGE_V09_HEARTBEAT_ENABLED=False,
            ), patch(
                "agentforge_django.runner.isolated_verification",
                side_effect=simulate_verification_with_interrupted_worker,
            ):
                result = run_job(job.pk)
            self.assertEqual(result.status, AgentJob.Status.BLOCKED)
            self.assertEqual(
                result.result["failure_class"], "INTERRUPTED_OR_ABANDONED_WORKER"
            )
            self.assertEqual(result.events.last().phase, "operator_recovery")
            self.assertTrue(verify_chain(result))

    def test_lease_token_fences_stale_worker(self):
        self.assertTrue(lease_owned(
            project_id=self.project.pk, job_id=self.job.pk,
            token=self.lease.owner_token,
        ))
        self.assertFalse(lease_owned(
            project_id=self.project.pk, job_id=self.job.pk,
            token=uuid.uuid4(),
        ))
        heartbeat = timezone.now()
        affected = JobLease.objects.filter(
            project=self.project, owner_token=uuid.uuid4()
        ).update(heartbeat_at=heartbeat)
        self.assertEqual(affected, 0)

    @override_settings(AGENTFORGE_V09_HEARTBEAT_ENABLED=True)
    def test_sqlite_heartbeat_fails_closed(self):
        guard = LeaseHeartbeat(
            project_id=self.project.pk, job_id=self.job.pk,
            token=self.lease.owner_token,
        )
        with self.assertRaises(BoundaryDenied):
            guard.start()

    def test_stale_start_without_heartbeat_opt_in_preserves_legacy_signal(self):
        JobLease.objects.filter(pk=self.lease.pk).update(
            acquired_at=timezone.now() - timedelta(minutes=40),
            heartbeat_at=timezone.now() - timedelta(minutes=40),
        )
        with override_settings(AGENTFORGE_V09_HEARTBEAT_ENABLED=False):
            record = lease_diagnostics(stale_after_minutes=20)[0]
        self.assertTrue(record["suspected_stale"])
        self.assertEqual(record["liveness"], "UNKNOWN_LEGACY_NO_HEARTBEAT")

    def test_old_start_with_recent_heartbeat_is_active_signal(self):
        JobLease.objects.filter(pk=self.lease.pk).update(
            acquired_at=timezone.now() - timedelta(minutes=40),
            heartbeat_at=timezone.now(),
        )
        JobLease.objects.filter(pk=self.lease.pk).update(heartbeat_enabled=True)
        with override_settings(AGENTFORGE_V09_HEARTBEAT_ENABLED=False):
            record = lease_diagnostics(stale_after_minutes=20)[0]
        self.assertFalse(record["suspected_stale"])
        self.assertEqual(record["liveness"], "RECENT_HEARTBEAT")
        self.assertTrue(record["age_seconds"] > 20 * 60)

    def test_stale_heartbeat_is_advisory_not_auto_recovery(self):
        JobLease.objects.filter(pk=self.lease.pk).update(
            heartbeat_enabled=True,
            heartbeat_at=timezone.now() - timedelta(minutes=30),
        )
        with override_settings(AGENTFORGE_V09_HEARTBEAT_ENABLED=True):
            record = lease_diagnostics(stale_after_minutes=20)[0]
        self.assertEqual(record["liveness"], "HEARTBEAT_OVERDUE_CHECK_PROCESS")
        self.assertTrue(record["suspected_stale"])
        self.assertFalse(record["recovery_allowed_automatically"])
        self.assertTrue(JobLease.objects.filter(pk=self.lease.pk).exists())
