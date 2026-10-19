"""V0.6 integration into existing immutable approval + status/audit gates."""
import os
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
from agentforge_django.v05_fixture import REQUEST, make_fixture
from agentforge_django.v06_fixture import FakeRepairModel


def evidence(ok):
    return {"backend": "docker-offline", "passed": ok,
            "business_tests_executed": True,
            "checks": [{"success": True, "returncode": 0},
                       {"success": ok, "returncode": 0 if ok else 1}]}


class V06JobTests(TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("Git not installed")
        temp = tempfile.TemporaryDirectory(prefix="af-v06-job-")
        self.addCleanup(temp.cleanup)
        self.root = make_fixture(Path(temp.name) / "project")
        def git(*args):
            return subprocess.run(
                ["git", *args], cwd=self.root, check=True,
                capture_output=True, text=True,
            ).stdout.strip()
        git("init", "-b", "main")
        git("config", "user.name", "Fixture Tester")
        git("config", "user.email", "fixture@example.invalid")
        git("add", ".")
        git("commit", "-m", "fixture baseline")
        self.head = git("rev-parse", "HEAD")
        self.admin = get_user_model().objects.create_superuser(
            "v06-op", "op@example.invalid", "local-testing"
        )
        self.project = ManagedProject.objects.create(
            name="v06-fixture", root_path=str(self.root), enabled=True,
            autonomous_enabled=True, run_business_tests=True,
            write_scopes=["app/**"], base_branch="main",
        )
        settings = override_settings(
            AGENTFORGE_ALLOWED_ROOTS=[str(self.root)],
            AGENTFORGE_ALLOW_AUTONOMOUS=True,
            AGENTFORGE_V05_ISOLATED_AUTONOMOUS=True,
            AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=True,
            AGENTFORGE_VERIFICATION_BACKEND="docker",
            AGENTFORGE_V06_BOUNDED_REPAIR=True,
            AGENTFORGE_V06_DEDICATED_WORKER=True,
        )
        settings.enable()
        self.addCleanup(settings.disable)
        self.job = AgentJob.objects.create(
            project=self.project, requested_by=self.admin,
            mode=AgentJob.Mode.AUTONOMOUS, request=REQUEST,
        )
        MutationApproval.objects.create(
            job=self.job, approved_by=self.admin,
            base_commit=self.head, approved_scopes=["app/**"],
            reason="Approve candidate source only with independent acceptance tests",
        )

    def test_dedicated_worker_role_required(self):
        with patch.dict(os.environ, {"AGENTFORGE_WORKER_ROLE": ""}):
            result = run_job(self.job.pk)
        self.assertEqual(result.status, AgentJob.Status.BLOCKED)
        self.assertTrue(verify_chain(result))

    def test_v06_repair_proposes_not_deploys(self):
        fake = FakeRepairModel()
        with patch.dict(os.environ, {"AGENTFORGE_WORKER_ROLE": "trusted-dedicated"}):
            with patch("agentforge_django.v05_broker.create_v05_broker",
                       return_value=fake) as maker, patch(
                       "agentforge_django.v06_repair.docker_verification",
                       side_effect=[evidence(False), evidence(True)]) as docker:
                result = run_job(self.job.pk)
        self.assertEqual(result.status, AgentJob.Status.PROPOSED)
        maker.assert_called_once_with(max_requests=5)
        self.assertEqual(docker.call_count, 2)
        self.assertEqual(result.result["budget"]["role_requests"], 5)
        self.assertEqual(result.result["repair_attempts"], 1)
        self.assertFalse(result.result["production_release_authorized"])
        self.assertTrue(verify_chain(result))
        self.assertIn("return a - b", (self.root / "app/views.py").read_text("utf-8"))
