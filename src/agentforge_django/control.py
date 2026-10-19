"""Server-side authorization and operator approval. No model writes before preflight."""

import subprocess

from django.conf import settings
from django.db import IntegrityError, transaction

from agentforge.execution_profiles import load_execution_profiles

from .audit import record
from .guard import (
    BoundaryDenied, checked_root, scope_within, scoped_file, validate_write_scopes,
)
from .models import AgentJob, ManagedProject, MutationApproval


def authorize_superuser(user):
    if not (user.is_authenticated and user.is_active and user.is_staff and user.is_superuser):
        raise BoundaryDenied("Only an active superuser may authorize engineering changes")


def create_pending_job(*, actor, project, mode, request_text=""):
    authorize_superuser(actor)
    if mode not in AgentJob.Mode.values:
        raise BoundaryDenied("Unsupported job mode")
    with transaction.atomic():
        project = ManagedProject.objects.select_for_update().get(pk=project.pk)
        if not project.enabled:
            raise BoundaryDenied("Disabled projects cannot accept new tasks")
        checked_root(project.root_path)
        if mode == AgentJob.Mode.VERIFY and not project.run_business_tests:
            raise BoundaryDenied("Business verification is disabled")
        if mode == AgentJob.Mode.AUTONOMOUS:
            if not project.autonomous_enabled or not getattr(
                settings, "AGENTFORGE_ALLOW_AUTONOMOUS", False
            ):
                raise BoundaryDenied("Autonomous capability is not enabled")
            if not request_text.strip():
                raise BoundaryDenied("Autonomous task requires a requirement")
        job = AgentJob.objects.create(
            project=project, requested_by=actor, mode=mode,
            request=request_text.strip(),
        )
        record(job, "operator_intake", "PENDING", {
            "actor_id": actor.pk, "mode": job.mode,
        })
        return job


def _git_read(root, *argv):
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *argv],
            shell=False, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BoundaryDenied("Cannot verify repository state") from exc
    if result.returncode:
        raise BoundaryDenied("Git preflight failed")
    return result.stdout.strip()


def approve_pending_job(*, actor, job_id, reason):
    authorize_superuser(actor)
    if not isinstance(reason, str) or not 12 <= len(reason.strip()) <= 1000:
        raise BoundaryDenied("Approval reason must be between 12 and 1000 characters")

    with transaction.atomic():
        job = AgentJob.objects.select_for_update().select_related("project").get(pk=job_id)
        project = ManagedProject.objects.select_for_update().get(pk=job.project_id)
        job.project = project
        if job.status != AgentJob.Status.PENDING or job.mode != AgentJob.Mode.AUTONOMOUS:
            raise BoundaryDenied("Only PENDING autonomous jobs can be approved")
        if MutationApproval.objects.filter(job=job).exists():
            raise BoundaryDenied("Approval already exists and cannot be replaced")
        if not (project.enabled and project.autonomous_enabled and project.run_business_tests):
            raise BoundaryDenied("Project autonomy or business test gates are OFF")
        if not getattr(settings, "AGENTFORGE_ALLOW_AUTONOMOUS", False):
            raise BoundaryDenied("Global autonomous switch is OFF")
        root = checked_root(project.root_path)
        scopes = validate_write_scopes(project.write_scopes)
        head = _git_read(root, "rev-parse", "--verify", "HEAD")
        if len(head) != 40:
            raise BoundaryDenied("Commit SHA cannot be pinned")
        if _git_read(root, "rev-parse", "--verify", project.base_branch) != head:
            raise BoundaryDenied("The approved base branch is not at HEAD")
        if _git_read(root, "status", "--porcelain"):
            raise BoundaryDenied("Only clean source repositories may be approved")
        profile_path = scoped_file(root, project.profiles_path)
        if not profile_path.is_file():
            raise BoundaryDenied("Execution profile is missing")
        try:
            loaded = load_execution_profiles(profile_path)
        except (ValueError, OSError) as exc:
            raise BoundaryDenied("Execution profile is invalid") from exc
        for name, profile in loaded.profiles.items():
            if not profile.write_scope:
                raise BoundaryDenied("Agent missing write scope")
            for scope in profile.write_scope:
                validate_write_scopes([scope])
                if not scope_within(scope, scopes):
                    raise BoundaryDenied(f"Agent {name} exceeds approved ceiling")
        try:
            approval = MutationApproval.objects.create(
                job=job, approved_by=actor, base_commit=head,
                approved_scopes=scopes, reason=reason.strip(),
            )
        except IntegrityError as exc:
            raise BoundaryDenied("Concurrent approval already exists") from exc
        record(job, "manual_approval", "APPROVED_FOR_CANDIDATE_ONLY", {
            "approver_id": actor.pk,
            "base_commit": head,
            "request_sha256": approval.request_sha256,
            "configuration_sha256": approval.configuration_sha256,
            "scope_count": len(scopes),
        })
        return approval
