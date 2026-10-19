"""Read-only worker lease health; operator recovery always manual."""
from datetime import timedelta

from django.utils import timezone
from django.conf import settings

from .models import JobLease


def lease_diagnostics(*, stale_after_minutes=20):
    if not 1 <= stale_after_minutes <= 1440:
        raise ValueError("stale_after_minutes must be between 1 and 1440")
    now = timezone.now()
    output = []
    for lease in JobLease.objects.select_related("job", "project").order_by("acquired_at"):
        age = max(0, int((now - lease.acquired_at).total_seconds()))
        heartbeat = getattr(lease, "heartbeat_at", None)
        heartbeat_age = None if heartbeat is None else max(
            0, int((now - heartbeat).total_seconds())
        )
        enabled = getattr(settings, "AGENTFORGE_V09_HEARTBEAT_ENABLED", False)
        if not enabled:
            liveness = "UNKNOWN_LEGACY_NO_HEARTBEAT"
            stale = age >= stale_after_minutes * 60
        elif heartbeat_age is None or heartbeat_age >= stale_after_minutes * 60:
            liveness = "HEARTBEAT_OVERDUE_CHECK_PROCESS"
            stale = True
        else:
            liveness = "RECENT_HEARTBEAT"
            stale = False
        output.append({
            "project_id": lease.project_id,
            "project": lease.project.name,
            "job_id": str(lease.job_id),
            "job_status": lease.job.status,
            "age_seconds": age,
            "suspected_stale": stale,
            "heartbeat_age_seconds": heartbeat_age,
            "liveness": liveness,
            "recovery_allowed_automatically": False,
        })
    return output


def job_lease_age(job):
    lease = JobLease.objects.filter(job=job).only("acquired_at").first()
    return None if not lease else max(
        0, int((timezone.now() - lease.acquired_at).total_seconds())
    )
