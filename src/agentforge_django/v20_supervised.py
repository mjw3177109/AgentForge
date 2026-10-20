"""V2.0 one-job dispatcher via the bounded OS child supervisor.

Never calls the unsafe in-process queue runner. Preflight before task selection;
no retry, no automatic lease recovery and no deployment.
"""
from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from .models import AgentJob
from .worker_readiness import worker_readiness


def process_one_supervised(*, mode="dedicated", timeout_seconds=780,
                           include_autonomous=False, include_verify=False):
    if type(timeout_seconds) is not int or not 60 <= timeout_seconds <= 3600:
        raise CommandError("Supervisor timeout must be 60–3600 seconds")
    if type(include_autonomous) is not bool or type(include_verify) is not bool:
        raise CommandError("Invalid supervised queue mode flags")
    ready = worker_readiness(mode=mode)
    if ready.get("ready_to_accept_candidate_only_jobs") is not True:
        raise CommandError("WORKER_PREFLIGHT_REJECTED_NO_TASK_CLAIM")
    modes = [AgentJob.Mode.AUDIT]
    if include_verify:
        modes.append(AgentJob.Mode.VERIFY)
    if include_autonomous:
        modes.append(AgentJob.Mode.AUTONOMOUS)
    job_id = AgentJob.objects.filter(
        status=AgentJob.Status.PENDING, mode__in=modes,
        project__enabled=True,
    ).order_by("created_at", "pk").values_list("pk", flat=True).first()
    if job_id is None:
        return {
            "status": "NO_PENDING_JOBS", "selected_job_id": None,
            "supervised": False, "production_release_authorized": False,
        }
    try:
        call_command(
            "supervise_agentforge_job", str(job_id),
            timeout_seconds=timeout_seconds, mode=mode, stdout=StringIO(),
        )
    except CommandError as exc:
        raise CommandError(
            "SUPERVISED_CHILD_FAILED_OR_TIMED_OUT; inspect worker lease, "
            "OS process group and Docker containers manually"
        ) from exc
    return {
        "status": "SUPERVISED_JOB_RETURNED", "selected_job_id": str(job_id),
        "supervised": True, "production_release_authorized": False,
    }
