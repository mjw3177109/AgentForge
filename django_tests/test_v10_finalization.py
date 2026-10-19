"""V1.0 deterministic finalization races and audit ordering."""
from datetime import timedelta
from unittest.mock import Mock
import uuid

from django.test import TestCase, override_settings
from django.utils import timezone

from agentforge_django.audit import record, verify_chain
from agentforge_django.job_finalization import finish_if_owner
from agentforge_django.models import AgentJob, JobLease, ManagedProject
from agentforge_django.recovery import recover_stopped_worker


class AtomicFinalizationTests(TestCase):
    def setUp(self):
        self.project = ManagedProject.objects.create(
            name="v10-fencing", root_path="/tmp/never-executed"
        )
        self.job = AgentJob.objects.create(
            project=self.project, status=AgentJob.Status.RUNNING
        )
        self.lease = JobLease.objects.create(
            project=self.project, job=self.job,
        )
        record(self.job, "intake", "CLAIMED")

    def finish(self, *, token=None, heartbeat=None, status=AgentJob.Status.PROPOSED):
        return finish_if_owner(
            self.job,
            token=token if token is not None else self.lease.owner_token,
            heartbeat=heartbeat,
            status=status,
            result={"candidate_patch": "synthetic", "production_release_authorized": False},
        )

    def test_active_owner_can_finalize_with_audit(self):
        self.assertTrue(self.finish())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AgentJob.Status.PROPOSED)
        self.assertTrue(verify_chain(self.job))
        self.assertEqual(self.job.events.last().decision, "PROPOSED")

    def test_foreign_token_cannot_finalize(self):
        self.assertFalse(self.finish(token=uuid.uuid4()))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AgentJob.Status.RUNNING)
        self.assertEqual(self.job.events.count(), 1)

    def test_recovery_wins_no_late_success_or_audit(self):
        recover_stopped_worker(self.job.pk, operator_confirmed=True)
        before = self.job.events.count()
        self.assertFalse(self.finish())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AgentJob.Status.BLOCKED)
        self.assertEqual(self.job.events.count(), before)
        self.assertEqual(self.job.events.last().phase, "operator_recovery")
        self.assertTrue(verify_chain(self.job))

    def test_missing_lease_leaves_job_for_operator(self):
        self.lease.delete()
        self.assertFalse(self.finish())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AgentJob.Status.RUNNING)
        self.assertEqual(self.job.events.count(), 1)

    def test_heartbeat_lost_blocks_candidate_in_same_transaction(self):
        guard = Mock()
        guard.beats = 4
        guard.lost.is_set.return_value = True
        with override_settings(AGENTFORGE_V09_HEARTBEAT_ENABLED=True):
            self.assertTrue(self.finish(heartbeat=guard))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AgentJob.Status.BLOCKED)
        self.assertEqual(self.job.result["failure_class"], "WORKER_HEARTBEAT_LOST")
        self.assertTrue(verify_chain(self.job))

    def test_stale_heartbeat_blocks_but_does_not_steal_lease(self):
        JobLease.objects.filter(pk=self.lease.pk).update(
            heartbeat_enabled=True,
            heartbeat_at=timezone.now() - timedelta(minutes=10),
        )
        with override_settings(AGENTFORGE_V09_HEARTBEAT_INTERVAL=10):
            self.assertTrue(self.finish())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AgentJob.Status.BLOCKED)
        self.assertEqual(
            self.job.result["failure_class"], "HEARTBEAT_OVERDUE_AT_FINAL_GATE"
        )
        self.assertTrue(JobLease.objects.filter(pk=self.lease.pk).exists())
        self.assertTrue(verify_chain(self.job))
