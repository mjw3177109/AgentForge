"""Control Center V0.3: permissions, approval preflight, CSRF and evidence exports."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from agentforge_django.approvals import approval_digests
from agentforge_django.audit import verify_chain
from agentforge_django.models import AgentJob, ManagedProject, MutationApproval


class ControlCenterTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="af-control-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "manage.py").write_text("# django fixture\n", "utf-8")
        self.project = ManagedProject.objects.create(
            name="trusted-project", root_path=str(self.root), enabled=True,
        )
        roots = override_settings(AGENTFORGE_ALLOWED_ROOTS=[str(self.root)])
        roots.enable()
        self.addCleanup(roots.disable)
        User = get_user_model()
        self.operator = User.objects.create_superuser(
            "root-admin", "root@example.test", "example-pass"
        )
        self.staff = User.objects.create_user(
            "staff-readonly", "staff@example.test", "example-pass", is_staff=True
        )
        self.new_url = reverse("agentforge_django:new_job")

    def submit(self, mode=AgentJob.Mode.AUDIT):
        return self.client.post(self.new_url, {
            "project": self.project.pk, "mode": mode,
            "request": "Verify that the change meets acceptance criteria",
        })

    def test_staff_is_read_only(self):
        job = AgentJob.objects.create(project=self.project)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("agentforge_django:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse(
            "agentforge_django:project_detail", args=[self.project.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse(
            "agentforge_django:job_detail", args=[job.pk])).status_code, 200)
        self.assertEqual(self.submit().status_code, 403)
        self.assertEqual(self.client.get(self.new_url).status_code, 403)
        self.assertEqual(self.client.get(reverse(
            "agentforge_django:download_evidence", args=[job.pk])).status_code, 403)

    def test_operator_submit_only_enqueues(self):
        self.client.force_login(self.operator)
        response = self.submit()
        self.assertEqual(response.status_code, 302)
        job = AgentJob.objects.get()
        self.assertEqual(job.status, AgentJob.Status.PENDING)
        self.assertIsNone(job.started_at)
        self.assertEqual(job.requested_by, self.operator)
        self.assertTrue(verify_chain(job))
        self.assertEqual(job.events.count(), 1)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.operator)
        self.assertEqual(client.post(self.new_url, {
            "project": self.project.pk, "mode": AgentJob.Mode.AUDIT,
        }).status_code, 403)
        self.assertEqual(AgentJob.objects.count(), 0)

    def test_disabled_project_is_blocked(self):
        self.client.force_login(self.operator)
        self.project.enabled = False
        self.project.save(update_fields=["enabled"])
        self.assertEqual(self.submit().status_code, 200)
        self.assertFalse(AgentJob.objects.exists())

    def test_autonomy_off_blocks_job_creation(self):
        self.client.force_login(self.operator)
        self.project.autonomous_enabled = True
        self.project.save(update_fields=["autonomous_enabled"])
        self.assertEqual(self.submit(AgentJob.Mode.AUTONOMOUS).status_code, 200)
        self.assertFalse(AgentJob.objects.exists())

    def test_evidence_export_redacts_generated_code(self):
        job = AgentJob.objects.create(project=self.project, result={
            "candidate_patch": "VERY_SECRET_DO_NOT_EXPORT",
            "patch_sha256": "a" * 64,
            "independent_verification": {
                "passed": True, "business_tests_executed": True,
                "checks": [{"success": True, "stdout": "VERY_SECRET_DO_NOT_EXPORT",
                            "stderr": "VERY_SECRET_DO_NOT_EXPORT", "returncode": 0}],
            },
        })
        self.client.force_login(self.operator)
        response = self.client.get(reverse(
            "agentforge_django:download_evidence", args=[job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"VERY_SECRET_DO_NOT_EXPORT", response.content)
        self.assertEqual(response["Cache-Control"], "no-store")
        result = json.loads(response.content)
        self.assertTrue(result["audit_hash_chain_valid"])
        self.assertFalse(result["production_release_authorized"])
        self.assertEqual(result["candidate_patch_sha256"], "a" * 64)

    def test_approval_requires_operator_and_post(self):
        job = AgentJob.objects.create(project=self.project, mode=AgentJob.Mode.AUTONOMOUS)
        url = reverse("agentforge_django:approve_job", args=[job.pk])
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url, {
            "reason": "Allow isolated changes for this requirement",
            "acknowledge": "on",
        }).status_code, 403)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {
            "reason": "A long enough human authorization reason",
        }).status_code, 302)
        self.assertFalse(MutationApproval.objects.exists())

    def test_approval_rejects_disabled_business_gate(self):
        self.client.force_login(self.operator)
        self.project.autonomous_enabled = True
        self.project.run_business_tests = False
        self.project.save(update_fields=["autonomous_enabled", "run_business_tests"])
        job = AgentJob.objects.create(
            project=self.project, mode=AgentJob.Mode.AUTONOMOUS, request="Change code"
        )
        with override_settings(AGENTFORGE_ALLOW_AUTONOMOUS=True):
            resp = self.client.post(reverse(
                "agentforge_django:approve_job", args=[job.pk]), {
                    "reason": "Must validate independent business test coverage",
                    "acknowledge": "on",
                })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(MutationApproval.objects.exists())

    def test_approval_pins_clean_git_head_and_request(self):
        if not shutil.which("git"):
            self.skipTest("git unavailable")
        (self.root / ".agent").mkdir()
        (self.root / "app").mkdir()
        (self.root / "app/sample.py").write_text("VALUE = 1\n", "utf-8")
        (self.root / ".agent/execution-profiles.yaml").write_text(
            "allowed_verification_executables: []\n"
            "agents:\n  backend:\n    read_scope: [app/**]\n"
            "    write_scope: [app/**]\n    deny_scope: [.agent/**]\n",
            "utf-8",
        )
        def git(*argv):
            return subprocess.run(
                ["git", *argv], cwd=self.root, check=True,
                text=True, capture_output=True,
            ).stdout.strip()
        git("init", "-b", "main")
        git("config", "user.name", "Unit Test")
        git("config", "user.email", "unit@example.test")
        git("add", ".")
        git("commit", "-m", "fixture")
        head = git("rev-parse", "HEAD")
        self.project.autonomous_enabled = True
        self.project.write_scopes = ["app/**"]
        self.project.save(update_fields=["autonomous_enabled", "write_scopes"])
        self.client.force_login(self.operator)
        with override_settings(AGENTFORGE_ALLOW_AUTONOMOUS=True):
            self.assertEqual(self.submit(AgentJob.Mode.AUTONOMOUS).status_code, 302)
            job = AgentJob.objects.get()
            url = reverse("agentforge_django:approve_job", args=[job.pk])
            self.assertEqual(self.client.post(url, {
                "reason": "Approval is limited to the app source and independent tests",
                "acknowledge": "on",
            }).status_code, 302)
            approval = MutationApproval.objects.get(job=job)
            self.assertEqual(approval.base_commit, head)
            self.assertEqual(approval.approved_scopes, ["app/**"])
            self.assertEqual(
                (approval.request_sha256, approval.configuration_sha256),
                approval_digests(job),
            )
            self.assertTrue(verify_chain(job))
            self.assertEqual(job.events.filter(phase="manual_approval").count(), 1)
            self.client.post(url, {
                "reason": "Repeated approval should never create a new authorization",
                "acknowledge": "on",
            })
            self.assertEqual(MutationApproval.objects.filter(job=job).count(), 1)
