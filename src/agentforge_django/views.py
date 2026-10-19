"""Staff read-only center; superuser-only POST intake/approval; never run code via HTTP."""

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .audit import verify_chain
from .control import approve_pending_job, create_pending_job
from .evidence_export import export_summary
from .forms import ApprovalForm, NewJobForm
from .guard import BoundaryDenied
from .health import fleet_summary, project_health
from .models import AgentJob, ManagedProject, MutationApproval


def _require_operator(request):
    user = request.user
    if not (user.is_active and user.is_staff and user.is_superuser):
        raise PermissionDenied("Superuser approval is required")


@staff_member_required
@require_GET
def dashboard(request):
    stats = fleet_summary()
    return render(request, "agentforge_django/dashboard.html", {
        "health_rows": stats["projects"],
        "total_projects": stats["total_projects"],
        "attention_projects": stats["attention_projects"],
        "verified_projects": stats["verified_projects"],
        "jobs": AgentJob.objects.select_related("project").all()[:30],
    })


@staff_member_required
@require_GET
def project_detail(request, project_id):
    project = get_object_or_404(ManagedProject, pk=project_id)
    return render(request, "agentforge_django/project_detail.html", {
        "project": project,
        "health": project_health(project),
        "jobs": AgentJob.objects.filter(project=project).order_by("-created_at")[:40],
        "busy": hasattr(project, "worker_lease"),
    })


@staff_member_required
@require_http_methods(["GET", "POST"])
def new_job(request):
    _require_operator(request)
    form = NewJobForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            job = create_pending_job(
                actor=request.user,
                project=form.cleaned_data["project"],
                mode=form.cleaned_data["mode"],
                request_text=form.cleaned_data["request"],
            )
        except (BoundaryDenied, ValueError, OSError) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(
                request, "任务已进入 PENDING 队列；网页不会执行 Agent。请由隔离 Worker 处理。",
            )
            return redirect("agentforge_django:job_detail", job_id=job.pk)
    if request.method == "GET" and request.GET.get("project"):
        form.fields["project"].initial = request.GET["project"]
    return render(request, "agentforge_django/new_job.html", {"form": form})


@staff_member_required
@require_GET
def job_detail(request, job_id):
    job = get_object_or_404(
        AgentJob.objects.select_related("project", "requested_by"), pk=job_id
    )
    checks = job.result.get("independent_verification", {})
    approval = MutationApproval.objects.filter(job=job).select_related("approved_by").first()
    can_approve = (
        request.user.is_superuser
        and job.mode == AgentJob.Mode.AUTONOMOUS
        and job.status == AgentJob.Status.PENDING
        and approval is None
    )
    return render(request, "agentforge_django/job_detail.html", {
        "job": job, "events": job.events.all()[:100],
        "audit_chain_ok": verify_chain(job),
        "failure_class": job.result.get("failure_class", ""),
        "failure_reason": job.result.get("reason", ""),
        "independent_checks": checks.get("checks", []) if isinstance(checks, dict) else [],
        "patch_hash": job.result.get("patch_sha256", ""),
        "patch_available": bool(job.result.get("candidate_patch")),
        "v06_budget": job.result.get("budget", {})
            if isinstance(job.result.get("budget"), dict) else {},
        "v06_repair_attempts": job.result.get("repair_attempts"),
        "v06_rounds": job.result.get("rounds", [])
            if isinstance(job.result.get("rounds"), list) else [],
        "approval": approval,
        "can_approve": can_approve,
        "approval_form": ApprovalForm(),
        "busy": hasattr(job.project, "worker_lease"),
    })


@staff_member_required
@require_POST
def approve_job(request, job_id):
    _require_operator(request)
    job = get_object_or_404(AgentJob, pk=job_id)
    form = ApprovalForm(request.POST)
    if not form.is_valid():
        messages.error(request, "审批失败：理由不足或未确认候选补丁权限范围。")
        return redirect("agentforge_django:job_detail", job_id=job_id)
    try:
        approve_pending_job(
            actor=request.user, job_id=job.pk,
            reason=form.cleaned_data["reason"],
        )
    except (BoundaryDenied, ValueError, OSError) as exc:
        messages.error(request, f"审批被安全门禁阻断：{exc}")
    else:
        messages.success(request, "审批已绑定 Git HEAD、任务内容与写入范围；未执行 Agent。")
    return redirect("agentforge_django:job_detail", job_id=job_id)


@staff_member_required
@require_GET
def download_evidence(request, job_id):
    _require_operator(request)
    job = get_object_or_404(AgentJob, pk=job_id)
    payload = export_summary(job)
    response = JsonResponse(payload, json_dumps_params={
        "ensure_ascii": False, "indent": 2,
    })
    response["Content-Disposition"] = (
        f'attachment; filename="agentforge-evidence-{job.pk}.json"'
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
