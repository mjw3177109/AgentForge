"""Read-only worker lease health; operator recovery always manual."""
from datetime import timedelta

from django.utils import timezone

from .models import JobLease


def lease_diagnostics(*, stale_after_minutes=20):
    if not 1 <= stale_after_minutes <= 1440:
        raise ValueError("stale_after_minutes must be between 1 and 1440")
    now = timezone.now()
    output = []
    for lease in JobLease.objects.select_related("job", "project").order_by("acquired_at"):
        age = max(0, int((now - lease.acquired_at).total_seconds()))
        output.append({
            "project_id": lease.project_id,
            "project": lease.project.name,
            "job_id": str(lease.job_id),
            "job_status": lease.job.status,
            "age_seconds": age,
            "suspected_stale": age >= stale_after_minutes * 60,
            "recovery_allowed_automatically": False,
        })
    return output


def job_lease_age(job):
    lease = JobLease.objects.filter(job=job).only("acquired_at").first()
    return None if not lease else max(
        0, int((timezone.now() - lease.acquired_at).total_seconds())
    )
