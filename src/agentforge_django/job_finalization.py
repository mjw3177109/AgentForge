"""Atomic PostgreSQL fencing for worker completion.

Both this finalizer and explicit operator recovery lock AgentJob before
JobLease, preventing a recovered/stolen worker from publishing a candidate.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .audit import record
from .models import AgentJob, JobLease


def finish_if_owner(job, *, token, heartbeat, status, result):
    if heartbeat is not None:
        heartbeat.stop()
        if not isinstance(result, dict):
            result = {"failure_class": "INVALID_EXECUTION_RESULT"}
        result["worker_heartbeat"] = {
            "enabled": bool(getattr(settings, "AGENTFORGE_V09_HEARTBEAT_ENABLED", False)),
            "beats": heartbeat.beats,
            "ownership_preserved": not heartbeat.lost.is_set(),
        }
        if heartbeat.lost.is_set():
            status = AgentJob.Status.BLOCKED
            result = {
                "failure_class": "WORKER_HEARTBEAT_LOST",
                "worker_heartbeat": result["worker_heartbeat"],
            }
    with transaction.atomic():
        locked = AgentJob.objects.select_for_update().get(pk=job.pk)
        if locked.status != AgentJob.Status.RUNNING:
            return False
        lease = JobLease.objects.select_for_update().filter(
            project_id=locked.project_id, job_id=job.pk, owner_token=token,
        ).first()
        if lease is None:
            # No longer owns the lock: never write status or audit in this job.
            # Operator must inspect/process-recover stale database state.
            return False
        if lease.heartbeat_enabled:
            interval = getattr(settings, "AGENTFORGE_V09_HEARTBEAT_INTERVAL", 10)
            if type(interval) is not int or not 1 <= interval <= 60:
                status = AgentJob.Status.BLOCKED
                result = {"failure_class": "INVALID_HEARTBEAT_POLICY"}
            elif timezone.now() - lease.heartbeat_at > timedelta(seconds=max(30, interval * 3)):
                status = AgentJob.Status.BLOCKED
                result = {"failure_class": "HEARTBEAT_OVERDUE_AT_FINAL_GATE"}
        locked.status = status
        locked.result = result
        locked.finished_at = timezone.now()
        locked.save(update_fields=["status", "result", "finished_at"])
        record(locked, "final_gate", status, {
            "failure_class": result.get("failure_class", "") if isinstance(result, dict) else "",
            "candidate_only": status == AgentJob.Status.PROPOSED,
        })
        return True
