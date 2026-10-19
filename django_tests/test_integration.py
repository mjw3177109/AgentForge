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

    def test_staff_only_dashboard(self):
        self.assertEqual(self.client.get("/agentforge/").status_code, 302)
        user = get_user_model().objects.create_user("staff", password="test-pass", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get("/agentforge/").status_code, 200)
