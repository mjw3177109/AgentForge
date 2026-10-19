"""V0.5 exercises actual Django job state/approval/audit end-to-end.

LLM is mocked and Docker validator mocked here; separate CI smoke exercises
a real Docker validator three times.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from agentforge_django.audit import verify_chain
from agentforge_django.models import AgentJob, ManagedProject, MutationApproval
from agentforge_django.runner import run_job
from agentforge_django.v05_fixture import REQUEST, ScriptedFakeAgent, make_fixture


class V05IntegratedJobTests(TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git not available")
        tmp = tempfile.TemporaryDirectory(prefix="af-v05-integrated-")
        self.addCleanup(tmp.cleanup)
        self.root = make_fixture(Path(tmp.name) / "git-project")
        def git(*args):
            return subprocess.run(
                ["git", *args], cwd=self.root, check=True,
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        git("init", "-b", "main")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "Test Operator")
        git("add", ".")
        git("commit", "-m", "fixture baseline")
        self.commit = git("rev-parse", "HEAD")
        self.operator = get_user_model().objects.create_superuser(
            "v05-admin", "v05@example.invalid", "testing-only"
        )
        self.project = ManagedProject.objects.create(
            name="v05-test", root_path=str(self.root), enabled=True,
            autonomous_enabled=True, write_scopes=["app/**"],
            run_business_tests=True, base_branch="main"
        )
        overrides = override_settings(
            AGENTFORGE_ALLOWED_ROOTS=[str(self.root)],
            AGENTFORGE_ALLOW_AUTONOMOUS=True,
            AGENTFORGE_V05_ISOLATED_AUTONOMOUS=True,
            AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=True,
            AGENTFORGE_VERIFICATION_BACKEND="docker",
        )
        overrides.enable()
        self.addCleanup(overrides.disable)

    def _job(self):
        job = AgentJob.objects.create(
            project=self.project, requested_by=self.operator,
            mode=AgentJob.Mode.AUTONOMOUS, request=REQUEST,
        )
        MutationApproval.objects.create(
            job=job, approved_by=self.operator,
            base_commit=self.commit, approved_scopes=["app/**"],
            reason="Explicitly permit a candidate patch without any deployment",
        )
        return job

    def _fake_verifier(self):
        return {
            "backend": "docker-offline", "passed": True,
            "business_tests_executed": True,
            "checks": [{"success": True, "returncode": 0},
                       {"success": True, "returncode": 0}],
        }

    def test_approved_job_proposed_only_and_source_unchanged(self):
        job = self._job()
        fake = ScriptedFakeAgent()
        with patch(
            "agentforge_django.v05_broker.create_v05_broker",
            return_value=fake,
        ), patch(
            "agentforge_django.v05_coding.isolated_verification",
            return_value=self._fake_verifier(),
        ):
            done = run_job(job.pk)
        self.assertEqual(done.status, AgentJob.Status.PROPOSED)
        self.assertEqual(fake.calls, 3)
        self.assertEqual(done.result["independent_verification"]["backend"], "docker-offline")
        self.assertFalse(done.result["production_release_authorized"])
        self.assertIn("return a + b", done.result["candidate_patch"])
        self.assertIn("return a - b", (self.root / "app/views.py").read_text("utf-8"))
        self.assertTrue(verify_chain(done))
        self.assertFalse(run_job(job.pk).status == AgentJob.Status.PASS)

    def test_mutated_request_invalidates_human_approval(self):
        job = self._job()
        job.request = REQUEST + " Also modify other files"
        job.save(update_fields=["request"])
        fake = ScriptedFakeAgent()
        with patch("agentforge_django.v05_broker.create_v05_broker", return_value=fake):
            done = run_job(job.pk)
        self.assertEqual(done.status, AgentJob.Status.BLOCKED)
        self.assertEqual(fake.calls, 0)
        self.assertTrue(verify_chain(done))

    def test_turn_off_flag_fails_closed(self):
        job = self._job()
        with override_settings(AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=False), patch(
            "agentforge_django.v05_broker.create_v05_broker"
        ) as client:
            done = run_job(job.pk)
        self.assertEqual(done.status, AgentJob.Status.BLOCKED)
        client.assert_not_called()
