"""V2.0: fail-closed bounded Worker supervisor; no paid API calls."""
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from agentforge_django.models import ManagedProject, AgentJob
from agentforge_django.queue import process_pending
from agentforge_django.v20_supervised import process_one_supervised


class SupervisedQueueTests(TestCase):
    def setUp(self):
        self.project = ManagedProject.objects.create(
            name="v20-test-project", root_path="/tmp/v20-fixture", enabled=True
        )

    def new_job(self, mode=AgentJob.Mode.AUDIT):
        return AgentJob.objects.create(project=self.project, mode=mode)

    def test_no_job_without_preflight_or_model(self):
        self.new_job()
        with patch("agentforge_django.v20_supervised.worker_readiness",
                   return_value={"ready_to_accept_candidate_only_jobs": False}), patch(
            "agentforge_django.v20_supervised.call_command"
        ) as call, patch("agentforge_django.v20_supervised.AgentJob.objects.filter") as query:
            with self.assertRaises(CommandError):
                process_one_supervised()
        call.assert_not_called()
        query.assert_not_called()

    def test_supervisor_selects_one_audit_job(self):
        self.new_job(AgentJob.Mode.AUTONOMOUS)
        target = self.new_job()
        with patch("agentforge_django.v20_supervised.worker_readiness",
                   return_value={"ready_to_accept_candidate_only_jobs": True}), patch(
            "agentforge_django.v20_supervised.call_command"
        ) as call:
            result = process_one_supervised(mode="ci-staging", timeout_seconds=120)
        self.assertEqual(result["selected_job_id"], str(target.pk))
        self.assertTrue(result["supervised"])
        self.assertFalse(result["production_release_authorized"])
        call.assert_called_once()
        self.assertEqual(call.call_args.kwargs["timeout_seconds"], 120)
        self.assertEqual(call.call_args.kwargs["mode"], "ci-staging")

    def test_autonomous_requires_explicit_selection(self):
        target = self.new_job(AgentJob.Mode.AUTONOMOUS)
        with patch("agentforge_django.v20_supervised.worker_readiness",
                   return_value={"ready_to_accept_candidate_only_jobs": True}), patch(
            "agentforge_django.v20_supervised.call_command"
        ) as call:
            self.assertEqual(process_one_supervised()["status"], "NO_PENDING_JOBS")
            result = process_one_supervised(include_autonomous=True)
        self.assertEqual(result["selected_job_id"], str(target.pk))
        call.assert_called_once()

    def test_supervisor_failure_never_retries_or_leaks_error(self):
        target = self.new_job()
        with patch("agentforge_django.v20_supervised.worker_readiness",
                   return_value={"ready_to_accept_candidate_only_jobs": True}), patch(
            "agentforge_django.v20_supervised.call_command",
            side_effect=CommandError("PRIVATE_SECRET_DO_NOT_EXPOSE")
        ) as call:
            with self.assertRaises(CommandError) as captured:
                process_one_supervised()
        self.assertEqual(call.call_count, 1)
        self.assertNotIn("PRIVATE_SECRET_DO_NOT_EXPOSE", str(captured.exception))
        target.refresh_from_db()
        self.assertEqual(target.status, AgentJob.Status.PENDING)

    def test_existing_production_queue_cannot_bypass_supervisor(self):
        self.new_job(AgentJob.Mode.AUTONOMOUS)
        with override_settings(
            AGENTFORGE_V06_DEDICATED_WORKER=True,
            AGENTFORGE_V09_HEARTBEAT_ENABLED=True,
        ):
            with self.assertRaisesRegex(ValueError, "supervised"):
                process_pending(include_autonomous=True)
            with self.assertRaisesRegex(ValueError, "supervised"):
                process_pending(include_verify=True)

    def test_invalid_timeout_denied_before_preflight(self):
        with patch("agentforge_django.v20_supervised.worker_readiness") as ready:
            for seconds in (0, 59, 3601, 30.0, True):
                with self.subTest(seconds=seconds), self.assertRaises(CommandError):
                    process_one_supervised(timeout_seconds=seconds)
        ready.assert_not_called()

    def test_os_supervisor_timeout_terminates_child_group_without_retry(self):
        from agentforge_django.management.commands.supervise_agentforge_job import Command
        job = self.new_job()
        with tempfile.TemporaryDirectory() as temp:
            manage = Path(temp) / "manage.py"
            manage.write_text("# synthetic\n", encoding="utf-8")
            child = MagicMock()
            child.pid = 42123
            child.wait.side_effect = [subprocess.TimeoutExpired("manage.py", 60), 0]
            with patch.dict(os.environ, {"AGENTFORGE_WORKER_ROLE": "trusted-dedicated"}), override_settings(
                AGENTFORGE_V06_DEDICATED_WORKER=True,
                AGENTFORGE_V09_HEARTBEAT_ENABLED=True,
            ), patch(
                "agentforge_django.management.commands.supervise_agentforge_job.worker_readiness",
                return_value={"ready_to_accept_candidate_only_jobs": True},
            ), patch(
                "agentforge_django.management.commands.supervise_agentforge_job.sys.argv",
                [str(manage), "supervise_agentforge_job"],
            ), patch(
                "agentforge_django.management.commands.supervise_agentforge_job.subprocess.Popen",
                return_value=child,
            ), patch(
                "agentforge_django.management.commands.supervise_agentforge_job.terminate_process_group",
                return_value=True,
            ) as terminated, patch(
                "agentforge_django.management.commands.supervise_agentforge_job.exclusive_subreaper",
                return_value=__import__("contextlib").nullcontext(),
            ), patch(
                "agentforge_django.management.commands.supervise_agentforge_job.drain_adopted_children",
                return_value=(True, False),
            ):
                with self.assertRaisesRegex(CommandError, "WORKER_TIMEOUT"):
                    Command().handle(
                        job_id=str(job.pk), timeout_seconds=60, mode="ci-staging"
                    )
            terminated.assert_called_once_with(child)
            self.assertEqual(child.wait.call_count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, AgentJob.Status.PENDING)
        self.assertFalse(job.leases.exists())
