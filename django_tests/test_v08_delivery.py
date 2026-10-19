"""V0.8 candidate-only delivery, integrity gates and read-only lease diagnostics."""
import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agentforge_django.approvals import approval_digests
from agentforge_django.audit import record, verify_chain
from agentforge_django.candidate_export import verified_patch
from agentforge_django.guard import BoundaryDenied
from agentforge_django.lease_diagnostics import lease_diagnostics
from agentforge_django.models import (
    AgentJob, JobLease, ManagedProject, MutationApproval,
)


class V08CandidateDeliveryTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.superuser = users.objects.create_superuser(
            "candidate-superuser", "superuser@example.invalid", "test-only"
        )
        self.staff = users.objects.create_user(
            "candidate-readonly", "staff@example.invalid",
            "test-only", is_staff=True,
        )
        self.project = ManagedProject.objects.create(
            name="candidate-fixture", root_path="/tmp/agentforge-synthetic",
            enabled=True, autonomous_enabled=True,
            write_scopes=["app/**"], base_branch="main",
        )
        self.patch_text = (
            "--- a/app/views.py\n"
            "+++ b/app/views.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def add(a, b):\n"
            "-    return a - b\n"
            "+    return a + b\n"
        )
        self.job = AgentJob.objects.create(
            project=self.project, requested_by=self.superuser,
            mode=AgentJob.Mode.AUTONOMOUS,
            status=AgentJob.Status.PROPOSED,
            request="Fix synthetic addition",
            result={
                "candidate_patch": self.patch_text,
                "patch_sha256": hashlib.sha256(
                    self.patch_text.encode("utf-8")
                ).hexdigest(),
                "source_files": ["app/views.py"],
                "production_release_authorized": False,
                "independent_verification": {
                    "backend": "docker-offline",
                    "passed": True,
                    "business_tests_executed": True,
                    "checks": [
                        {"success": True, "returncode": 0},
                        {"success": True, "returncode": 0},
                    ],
                },
            },
        )
        MutationApproval.objects.create(
            job=self.job, approved_by=self.superuser,
            base_commit="a" * 40, approved_scopes=["app/**"],
            reason="Synthetic scope-limited approval for regression testing",
        )
        record(self.job, "manual_approval", "APPROVED_FOR_CANDIDATE_ONLY")
        record(self.job, "final_gate", "PROPOSED")
        self.url = reverse("agentforge_django:download_candidate_patch", args=[self.job.pk])

    def test_superuser_can_download_without_mutating_data(self):
        self.client.force_login(self.superuser)
        before = self.job.events.count()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), self.patch_text)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-AgentForge-Candidate-Only"], "true")
        self.assertEqual(response["X-AgentForge-Patch-SHA256"],
                         self.job.result["patch_sha256"])
        self.assertEqual(self.job.events.count(), before)
        self.assertTrue(verify_chain(self.job))

    def test_staff_cannot_download_candidate_source(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_corrupt_hash_and_non_proposed_are_forbidden(self):
        self.client.force_login(self.superuser)
        original = self.job.result.copy()
        self.job.result = {**original, "patch_sha256": "b" * 64}
        self.job.save(update_fields=["result"])
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.job.result = original
        self.job.status = AgentJob.Status.FAIL
        self.job.save(update_fields=["result", "status"])
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_policy_mutation_invalidates_export(self):
        self.project.write_scopes = ["elsewhere/**"]
        self.project.save(update_fields=["write_scopes"])
        with self.assertRaises(BoundaryDenied):
            verified_patch(self.job)

    def test_missing_tests_or_forged_header_denied(self):
        original = dict(self.job.result)
        forged = dict(original)
        forged["candidate_patch"] = self.patch_text.replace(
            "+++ b/app/views.py", "+++ b/app/settings.py"
        )
        forged["patch_sha256"] = hashlib.sha256(
            forged["candidate_patch"].encode("utf-8")
        ).hexdigest()
        self.job.result = forged
        self.job.save(update_fields=["result"])
        with self.assertRaises(BoundaryDenied):
            verified_patch(self.job)
        original["independent_verification"] = {
            **original["independent_verification"], "business_tests_executed": False,
        }
        self.job.result = original
        self.job.save(update_fields=["result"])
        with self.assertRaises(BoundaryDenied):
            verified_patch(self.job)


class V08LeaseInspectionTests(TestCase):
    def test_lease_stale_is_advisory_and_never_recovered(self):
        project = ManagedProject.objects.create(
            name="lease-v08", root_path="/tmp/unmanaged",
        )
        job = AgentJob.objects.create(
            project=project, status=AgentJob.Status.RUNNING,
        )
        lease = JobLease.objects.create(project=project, job=job)
        JobLease.objects.filter(pk=lease.pk).update(
            acquired_at=timezone.now() - timedelta(minutes=21)
        )
        before_status = job.status
        report = lease_diagnostics(stale_after_minutes=20)
        self.assertEqual(report[0]["job_id"], str(job.pk))
        self.assertTrue(report[0]["suspected_stale"])
        self.assertFalse(report[0]["recovery_allowed_automatically"])
        job.refresh_from_db()
        self.assertEqual(job.status, before_status)
        self.assertTrue(JobLease.objects.filter(pk=lease.pk).exists())

    def test_reject_invalid_age_threshold(self):
        with self.assertRaises(ValueError):
            lease_diagnostics(stale_after_minutes=0)
