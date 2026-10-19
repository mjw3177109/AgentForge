import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from agentforge_django.audit import verify_chain
from agentforge_django.guard import BoundaryDenied, safe_relative, scope_within
from agentforge_django.models import AgentJob, ManagedProject
from agentforge_django.runner import run_job


class ScopeTests(TestCase):
    def test_path_traversal_denied(self):
        for raw in ("../settings.py", "/etc/passwd", "a/../b", "a\\b", ".git/config", ".env"):
            with self.subTest(raw=raw), self.assertRaises(BoundaryDenied):
                safe_relative(raw)

    def test_restrict_scope_ceiling(self):
        self.assertTrue(scope_within("app/views.py", ["app/**"]))
        self.assertTrue(scope_within("app/sub/**", ["app/**"]))
        self.assertFalse(scope_within("admin/**", ["app/**"]))


class JobTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="af-django-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "manage.py").write_text("print('do not run me')\n", "utf-8")
        (self.root / "sample.py").write_text("VALUE = 1\n", "utf-8")
        self.project = ManagedProject.objects.create(
            name="sample", root_path=str(self.root), enabled=True,
        )
        self.allowed = override_settings(AGENTFORGE_ALLOWED_ROOTS=[str(self.root)])
        self.allowed.enable()
        self.addCleanup(self.allowed.disable)

    def test_audit_is_read_only_and_idempotent(self):
        job = AgentJob.objects.create(project=self.project, mode=AgentJob.Mode.AUDIT)
        self.assertEqual(run_job(job.pk).status, AgentJob.Status.PASS)
        self.assertTrue(verify_chain(job))
        count = job.events.count()
        self.assertEqual(run_job(job.pk).status, AgentJob.Status.PASS)
        self.assertEqual(job.events.count(), count)
        self.assertEqual((self.root / "sample.py").read_text("utf-8"), "VALUE = 1\n")

    def test_disabled_project_fails_closed(self):
        self.project.enabled = False
        self.project.save()
        job = AgentJob.objects.create(project=self.project)
        self.assertEqual(run_job(job.pk).status, AgentJob.Status.BLOCKED)

    def test_autonomous_needs_global_switch(self):
        job = AgentJob.objects.create(project=self.project, mode=AgentJob.Mode.AUTONOMOUS,
                                      request="Change sample.py")
        self.assertEqual(run_job(job.pk).status, AgentJob.Status.BLOCKED)
        self.assertEqual((self.root / "sample.py").read_text("utf-8"), "VALUE = 1\n")

    def test_invalid_syntax_fails_not_passes(self):
        (self.root / "sample.py").write_text("def broken(:\n", "utf-8")
        job = AgentJob.objects.create(project=self.project, mode=AgentJob.Mode.AUDIT)
        self.assertEqual(run_job(job.pk).status, AgentJob.Status.FAIL)

    def test_disallowed_root_blocked(self):
        with override_settings(AGENTFORGE_ALLOWED_ROOTS=[]):
            job = AgentJob.objects.create(project=self.project)
            self.assertEqual(run_job(job.pk).status, AgentJob.Status.BLOCKED)

    def test_zero_business_tests_are_not_pass(self):
        (self.root / "manage.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "Path('sandbox_marker.txt').write_text('executed')\n"
            "print('Ran 0 tests' if 'test' in sys.argv else 'System check identified no issues')\n",
            "utf-8",
        )
        job = AgentJob.objects.create(project=self.project, mode=AgentJob.Mode.VERIFY)
        with override_settings(
            AGENTFORGE_VERIFICATION_BACKEND="local",
            AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY=True,
        ):
            self.assertEqual(run_job(job.pk).status, AgentJob.Status.FAIL)
        self.assertFalse((self.root / "sandbox_marker.txt").exists())
        self.assertTrue(verify_chain(job))

    def test_staff_only_dashboard(self):
        self.assertEqual(self.client.get("/agentforge/").status_code, 302)
        user = get_user_model().objects.create_user("staff", password="test-pass", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get("/agentforge/").status_code, 200)


class QueueAndRecoveryTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="af-queue-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "manage.py").write_text("print('not called in AUDIT')\n", "utf-8")
        (self.root / "app.py").write_text("X = 1\n", "utf-8")
        self.project = ManagedProject.objects.create(
            name="queue-example", root_path=str(self.root), enabled=True
        )
        self.allowed = override_settings(AGENTFORGE_ALLOWED_ROOTS=[str(self.root)])
        self.allowed.enable()
        self.addCleanup(self.allowed.disable)

    def test_queue_default_audit_only_and_finite(self):
        from agentforge_django.queue import process_pending
        for _ in range(3):
            AgentJob.objects.create(project=self.project, mode=AgentJob.Mode.AUDIT)
        verify = AgentJob.objects.create(project=self.project, mode=AgentJob.Mode.VERIFY)
        result = process_pending(max_jobs=2)
        self.assertEqual(len(result["processed"]), 2)
        self.assertEqual(AgentJob.objects.filter(status=AgentJob.Status.PASS).count(), 2)
        verify.refresh_from_db()
        self.assertEqual(verify.status, AgentJob.Status.PENDING)

    def test_existing_lease_does_not_steal_or_run(self):
        from agentforge_django.models import JobLease
        pending = AgentJob.objects.create(project=self.project)
        occupying = AgentJob.objects.create(project=self.project, status=AgentJob.Status.RUNNING)
        lease = JobLease.objects.create(project=self.project, job=occupying)
        self.assertEqual(run_job(pending.pk).status, AgentJob.Status.PENDING)
        self.assertEqual(JobLease.objects.get(pk=lease.pk).job_id, occupying.pk)
        self.assertEqual(pending.events.count(), 0)

    def test_manual_recovery_is_blocked_by_default(self):
        from agentforge_django.models import JobLease
        from agentforge_django.recovery import RecoveryDenied, recover_stopped_worker
        job = AgentJob.objects.create(project=self.project, status=AgentJob.Status.RUNNING)
        JobLease.objects.create(project=self.project, job=job)
        with self.assertRaises(RecoveryDenied):
            recover_stopped_worker(job.pk)
        self.assertEqual(recover_stopped_worker(
            job.pk, operator_confirmed=True).status, AgentJob.Status.BLOCKED)
        self.assertFalse(JobLease.objects.filter(project=self.project).exists())
        self.assertTrue(verify_chain(job))
        job.refresh_from_db()
        self.assertEqual(job.result["failure_class"], "INTERRUPTED_OR_ABANDONED_WORKER")

    def test_approval_is_bound_to_request_and_policy(self):
        from agentforge_django.models import MutationApproval
        from agentforge_django.approvals import approval_digests
        staff = get_user_model().objects.create_user(
            "reviewer-unique", password="test-pass", is_staff=True
        )
        self.project.autonomous_enabled = True
        self.project.write_scopes = ["app/**"]
        self.project.save()
        job = AgentJob.objects.create(
            project=self.project, mode=AgentJob.Mode.AUTONOMOUS, request="Fix app module"
        )
        approval = MutationApproval.objects.create(
            job=job, approved_by=staff, base_commit="0" * 40,
            approved_scopes=["app/**"], reason="Manual approval for this exact job"
        )
        self.assertEqual(
            (approval.request_sha256, approval.configuration_sha256),
            approval_digests(job),
        )
        job.request = "Modify something else"
        job.save(update_fields=["request"])
        from agentforge_django.approvals import approval_digests
        self.assertNotEqual(approval.request_sha256, approval_digests(job)[0])
        with override_settings(AGENTFORGE_ALLOW_AUTONOMOUS=True):
            self.assertEqual(run_job(job.pk).status, AgentJob.Status.BLOCKED)
        self.assertTrue(verify_chain(job))
        with self.assertRaises(ValueError):
            approval.reason = "tampered"
            approval.save()

    def test_verify_requires_business_test_gate(self):
        self.project.run_business_tests = False
        self.project.save(update_fields=["run_business_tests"])
        job = AgentJob.objects.create(project=self.project, mode=AgentJob.Mode.VERIFY)
        self.assertEqual(run_job(job.pk).status, AgentJob.Status.BLOCKED)
        job.refresh_from_db()
        self.assertIn("business tests", job.result.get("reason", "").lower())

    def test_audit_does_not_claim_verified_business(self):
        from agentforge_django.health import project_health
        job = AgentJob.objects.create(project=self.project)
        run_job(job.pk)
        summary = project_health(self.project)
        self.assertFalse(summary["verified_business_tests"])
        self.assertEqual(summary["state"], "AUDIT_ONLY_OR_UNVERIFIED")
        self.assertEqual(summary["observed_completion_pct"], 100.0)
