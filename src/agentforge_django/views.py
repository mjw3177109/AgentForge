from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, render

from .audit import verify_chain
from .health import fleet_summary
from .models import AgentJob


@staff_member_required
def dashboard(request):
    stats = fleet_summary()
    return render(request, "agentforge_django/dashboard.html", {
        "health_rows": stats["projects"],
        "total_projects": stats["total_projects"],
        "attention_projects": stats["attention_projects"],
        "verified_projects": stats["verified_projects"],
        "jobs": AgentJob.objects.select_related("project").all()[:50],
    })


@staff_member_required
def job_detail(request, job_id):
    job = get_object_or_404(
        AgentJob.objects.select_related("project", "requested_by"), pk=job_id
    )
    checks = job.result.get("independent_verification", {})
    return render(request, "agentforge_django/job_detail.html", {
        "job": job,
        "events": job.events.all()[:100],
        "audit_chain_ok": verify_chain(job),
        "failure_class": job.result.get("failure_class", ""),
        "failure_reason": job.result.get("reason", ""),
        "independent_checks": checks.get("checks", []),
        "patch_hash": job.result.get("patch_sha256", ""),
        "patch_available": bool(job.result.get("candidate_patch")),
    })
