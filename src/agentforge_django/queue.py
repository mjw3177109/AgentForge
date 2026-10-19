"""Database-backed bounded dispatcher, designed for an operator-controlled worker."""

from .models import AgentJob
from .runner import run_job


def process_pending(*, max_jobs=1, include_verify=False, include_autonomous=False, project_id=None):
    if not isinstance(max_jobs, int) or not 1 <= max_jobs <= 100:
        raise ValueError("max_jobs must be between 1 and 100")
    modes = [AgentJob.Mode.AUDIT]
    if include_verify:
        modes.append(AgentJob.Mode.VERIFY)
    if include_autonomous:
        modes.append(AgentJob.Mode.AUTONOMOUS)
    queryset = AgentJob.objects.filter(
        status=AgentJob.Status.PENDING, mode__in=modes
    ).order_by("created_at", "pk")
    if project_id is not None:
        queryset = queryset.filter(project_id=project_id)

    # Snapshot a finite candidate pool; do not race with newly submitted jobs
    # and do not spin infinitely on a project occupied by another worker.
    candidates = list(queryset.values_list("pk", flat=True)[:max_jobs * 10])
    completed, skipped = [], []
    for job_id in candidates:
        if len(completed) >= max_jobs:
            break
        job = run_job(job_id)
        if job.status == AgentJob.Status.PENDING:
            skipped.append(str(job.pk))
        else:
            completed.append({"job_id": str(job.pk), "status": job.status})
    return {"processed": completed, "busy_or_skipped": skipped, "selected_modes": modes}
