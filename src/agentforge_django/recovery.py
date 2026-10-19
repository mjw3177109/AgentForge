"""Operator-only recovery after the worker process is confirmed stopped."""

from django.db import transaction
from django.utils import timezone

from .audit import record
from .models import AgentJob, JobLease


class RecoveryDenied(RuntimeError):
    pass


def recover_stopped_worker(job_id, *, operator_confirmed=False):
    if not operator_confirmed:
        raise RecoveryDenied("Operator must explicitly confirm the worker has stopped")
    with transaction.atomic():
        job = AgentJob.objects.select_for_update().get(pk=job_id)
        lease = JobLease.objects.select_for_update().filter(
            project=job.project, job=job
        ).first()
        if lease is None:
            raise RecoveryDenied("No matching lease exists; nothing may be recovered")
        # Never silently retry or mark a lost run successful.
        if job.status == AgentJob.Status.RUNNING:
            job.status = AgentJob.Status.BLOCKED
            job.result = {
                "failure_class": "INTERRUPTED_OR_ABANDONED_WORKER",
                "reason": "Operator confirmed worker has stopped; resubmit a NEW job",
            }
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "result", "finished_at"])
            record(job, "operator_recovery", "BLOCKED", {
                "failure_class": "INTERRUPTED_OR_ABANDONED_WORKER",
            })
        elif job.status != AgentJob.Status.PENDING:
            # A completed job's stale lease is cleanup-only.
            record(job, "operator_recovery", "LEASE_CLEANUP", {
                "existing_status": job.status,
            })
        lease.delete()
    return job
