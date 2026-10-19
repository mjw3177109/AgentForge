"""Real RDBMS compatibility of approval audit decisions."""
from django.test import TestCase

from agentforge_django.audit import record, verify_chain
from agentforge_django.models import AgentJob, ManagedProject


class PostgreSQLContractTests(TestCase):
    def test_human_approval_long_decision_fits_audit_column(self):
        project = ManagedProject.objects.create(name="audit-long-regression",
                                                 root_path="/tmp/not-a-real-workspace")
        job = AgentJob.objects.create(project=project)
        decision = "APPROVED_FOR_CANDIDATE_ONLY"
        event = record(job, "manual_approval", decision, {"actor_id": 1})
        event.refresh_from_db()
        self.assertEqual(event.decision, decision)
        self.assertTrue(verify_chain(job))
        self.assertEqual(AgentJob.objects.get(pk=job.pk).status, AgentJob.Status.PENDING)
