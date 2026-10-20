"""One-shot OS-level process timeout for trusted Linux worker jobs.

The job process is killed as a process group. Docker daemon containers may
outlive the CLI and MUST be manually inspected before operator lease recovery.
"""
import os
from pathlib import Path
import subprocess
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from agentforge_django.models import AgentJob, JobLease
from agentforge_django.worker_readiness import worker_readiness
from agentforge_django.v21_process_guard import terminate_process_group, group_quiescent


class Command(BaseCommand):
    help = "Run exactly one queued job in a bounded separate process (Linux worker only)."

    def add_arguments(self, parser):
        parser.add_argument("job_id")
        parser.add_argument("--timeout-seconds", type=int, default=900)
        parser.add_argument("--mode", choices=("dedicated", "ci-staging"), default="dedicated")

    def handle(self, *args, **options):
        if (
            os.name != "posix"
            or os.environ.get("AGENTFORGE_WORKER_ROLE") != "trusted-dedicated"
            or not getattr(settings, "AGENTFORGE_V06_DEDICATED_WORKER", False)
            or not getattr(settings, "AGENTFORGE_V09_HEARTBEAT_ENABLED", False)
        ):
            raise CommandError("Dedicated Linux Worker and PostgreSQL heartbeat required")
        # Direct invocations must honor the same gate as the systemd dispatcher.
        if worker_readiness(mode=options["mode"]).get("ready_to_accept_candidate_only_jobs") is not True:
            raise CommandError("WORKER_PREFLIGHT_REJECTED_NO_TASK_CLAIM")
        seconds = options["timeout_seconds"]
        if not 60 <= seconds <= 3600:
            raise CommandError("timeout-seconds must be between 60 and 3600")
        job = AgentJob.objects.get(pk=options["job_id"])
        if job.status != AgentJob.Status.PENDING:
            raise CommandError("Only PENDING jobs can enter the supervised worker")
        manage = Path(sys.argv[0]).resolve()
        if manage.name != "manage.py" or not manage.is_file():
            raise CommandError("Invoke this command through the trusted Django manage.py")
        command = [sys.executable, str(manage), "run_agentforge_job", str(job.pk)]
        # No pipe capture: target code logs may contain private data.
        child = subprocess.Popen(
            command, shell=False, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            code = child.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            # A direct child may exit on TERM while its grandchildren keep
            # running. V2.1 always SIGKILLs the entire original process group
            # and checks that no executable group members remain.
            terminated = terminate_process_group(child)
            if not terminated:
                raise CommandError(
                    "WORKER_TIMEOUT_PROCESS_EXIT_UNVERIFIED; manual process, "
                    "Docker and lease inspection required"
                )
            raise CommandError(
                "WORKER_TIMEOUT: OS process group quiescent; still inspect "
                "Docker daemon containers and recover lease manually"
            )
        if not group_quiescent(child.pid):
            # A child returning zero is NOT enough if it leaves descendants.
            terminate_process_group(child, term_grace=1.0, kill_grace=5.0)
            raise CommandError(
                "WORKER_CHILD_DESCENDANTS_REMAIN_OR_UNVERIFIED; no successful "
                "finalization claim, inspect Docker and lease manually"
            )
        job.refresh_from_db()
        if (code == 0 and (
            job.status not in (AgentJob.Status.PASS, AgentJob.Status.PROPOSED)
            or JobLease.objects.filter(project=job.project, job=job).exists()
        )):
            raise CommandError("Worker exit code is not trusted proof of finalized ownership")
        if code != 0:
            raise CommandError(
                "Worker child failed; inspect redacted job state and "
                "lease diagnostics; no automatic retry or lease recovery"
            )
        self.stdout.write(f"{job.pk}: {job.status}")
