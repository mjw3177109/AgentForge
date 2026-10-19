"""Synchronous job worker. Execute with management command, never an HTTP handler."""

import hashlib
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .audit import record
from .guard import (
    BoundaryDenied, checked_root, scope_within, scoped_file, validate_write_scopes,
)
from .inspection import inspect_python, sanitized_manifest
from .models import AgentJob
from .planning import advisor
from .verification import isolated_verification


def _git(root, *args, timeout=30):
    done = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        shell=False, timeout=timeout,
    )
    if done.returncode:
        raise BoundaryDenied(f"Git preflight failed: {args[0]}")
    return done.stdout.strip()


def _autonomous(job, root):
    project = job.project
    if not getattr(settings, "AGENTFORGE_ALLOW_AUTONOMOUS", False):
        raise BoundaryDenied("Global autonomous feature switch is OFF")
    if not project.autonomous_enabled:
        raise BoundaryDenied("Project autonomous feature switch is OFF")
    if not job.request.strip():
        raise BoundaryDenied("Autonomous job requires a user requirement")
    try:
        approval = job.approval
    except Exception as exc:
        from .models import MutationApproval
        if isinstance(exc, MutationApproval.DoesNotExist):
            raise BoundaryDenied("Signed human approval is missing") from exc
        raise
    if not approval.approved_by.is_staff or not approval.approved_by.is_active:
        raise BoundaryDenied("Approval must be from an active staff member")
    permitted = validate_write_scopes(project.write_scopes)
    approved = validate_write_scopes(approval.approved_scopes)
    if permitted != approved:
        raise BoundaryDenied("Scope changed after approval; reapproval required")
    head = _git(root, "rev-parse", "--verify", "HEAD")
    if head != approval.base_commit:
        raise BoundaryDenied("Git HEAD changed since human approval")
    if _git(root, "status", "--porcelain"):
        raise BoundaryDenied("Source repository must be clean")
    if _git(root, "rev-parse", "--verify", project.base_branch) != head:
        raise BoundaryDenied("Approved base_branch must match current HEAD")

    profiles_path = scoped_file(root, project.profiles_path)
    if not profiles_path.is_file():
        raise BoundaryDenied("Explicit execution profile YAML missing")
    from agentforge.execution_profiles import load_execution_profiles
    loaded = load_execution_profiles(profiles_path)
    for agent, profile in loaded.profiles.items():
        for scope in profile.write_scope:
            validate_write_scopes([scope])
            if not scope_within(scope, approved):
                raise BoundaryDenied(f"Agent '{agent}' requests unapproved scope: {scope}")
        if not profile.write_scope:
            raise BoundaryDenied(f"Agent '{agent}' has no permitted write scope")
    from agentforge.autonomous import AutonomousDevelopmentPipeline
    from agentforge.runtime_config import ExternalLLMSettings

    with tempfile.TemporaryDirectory(prefix="agentforge-django-autonomous-") as temp:
        sandbox = Path(temp) / "workspace"
        clone = subprocess.run(
            ["git", "clone", "--no-local", "--", str(root), str(sandbox)],
            capture_output=True, text=True, timeout=120, shell=False,
        )
        if clone.returncode:
            raise BoundaryDenied("Cannot create isolated repository clone")
        _git(sandbox, "config", "user.name", "AgentForge Django")
        _git(sandbox, "config", "user.email", "agentforge@localhost.invalid")
        pipeline = AutonomousDevelopmentPipeline(
            client=ExternalLLMSettings.from_env().client(),
            repo_root=sandbox,
            profiles=loaded.profiles,
            allowed_verification_executables=loaded.allowed_executables,
            max_coding_attempts=2,
            max_review_rounds=2,
        )
        result = pipeline.run(
            job.request, base_branch=project.base_branch,
            feature_branch=f"feature/django-{job.id.hex[:16]}",
            push=False, create_pr=False,
        )
        summary = {
            "core_status": result.status,
            "review": result.review.model_dump() if result.review else None,
            "task_runs": [item.model_dump() for item in result.task_runs],
            "feature_branch": result.feature_branch,
            "release": "NOT_AUTHORIZED",
        }
        record(job, "reviewer", result.review.status if result.review else "NOT_RUN",
               {"status": result.status, "task_count": len(result.task_runs)})
        if result.status != "SUCCESS" or not result.review or result.review.status != "APPROVE":
            return AgentJob.Status.BLOCKED, summary
        independent = isolated_verification(
            sandbox, with_tests=project.run_business_tests,
        )
        record(job, "validator", "PASS" if independent["passed"] else "FAIL",
               {"checks": [{"argv": c["argv"], "success": c["success"]}
                           for c in independent["checks"]]})
        summary["independent_verification"] = independent
        if not project.run_business_tests:
            # Explicitly configured unit/behavioral tests are mandatory for auto-code acceptance.
            return AgentJob.Status.BLOCKED, {
                **summary, "reason": "Business test gate disabled; cannot propose autonomous patch"}
        if not independent["passed"]:
            return AgentJob.Status.FAIL, summary
        patch = _git(sandbox, "diff", "--binary",
                     f"{project.base_branch}...HEAD", timeout=60)
        if not patch:
            return AgentJob.Status.BLOCKED, {**summary, "reason": "No candidate diff"}
        encoded = patch.encode("utf-8")
        if len(encoded) > 200_000:
            return AgentJob.Status.BLOCKED, {
                **summary, "reason": "Patch exceeds 200 KB evidence limit"}
        summary["patch_sha256"] = hashlib.sha256(encoded).hexdigest()
        summary["candidate_patch"] = patch
        summary["candidate_only"] = True
        return AgentJob.Status.PROPOSED, summary


def run_job(job_id):
    """Idempotent claim: a pending job can be picked up only once."""
    claimed = AgentJob.objects.filter(pk=job_id, status=AgentJob.Status.PENDING).update(
        status=AgentJob.Status.RUNNING, started_at=timezone.now(),
    )
    job = AgentJob.objects.select_related("project").get(pk=job_id)
    if not claimed:
        return job

    status, result = AgentJob.Status.BLOCKED, {}
    try:
        record(job, "intake", "CLAIMED", {"mode": job.mode})
        if not job.project.enabled:
            raise BoundaryDenied("Project is disabled by default")
        root = checked_root(job.project.root_path)
        manifest = inspect_python(root)
        record(job, "planner", "PASS", {
            "python_files": manifest["python_files"],
            "django_detected": manifest["django_detected"],
        })
        if not manifest["django_detected"]:
            raise BoundaryDenied("The selected root is not a Django project")
        if not manifest["static_pass"]:
            result = {"static": manifest}
            status = AgentJob.Status.FAIL
        elif job.mode == AgentJob.Mode.AUDIT:
            proposed = advisor(job.request, sanitized_manifest(root))
            result = {"static": manifest, "ai_plan": proposed,
                      "business_tests": "NOT_RUN", "scope": "READ_ONLY"}
            record(job, "reviewer", "PASS", {"static_findings": len(manifest["findings"])})
            status = AgentJob.Status.PASS
        elif job.mode == AgentJob.Mode.VERIFY:
            independent = isolated_verification(
                root, with_tests=job.project.run_business_tests,
            )
            result = {"static": manifest, "independent_verification": independent}
            status = AgentJob.Status.PASS if independent["passed"] else AgentJob.Status.FAIL
            record(job, "validator", status, {
                "checks": [{"argv": c["argv"], "success": c["success"]}
                           for c in independent["checks"]],
                "business_tests_executed": independent["business_tests_executed"],
            })
        elif job.mode == AgentJob.Mode.AUTONOMOUS:
            status, result = _autonomous(job, root)
        else:
            raise BoundaryDenied("Unrecognized job mode")
    except BoundaryDenied as exc:
        status, result = AgentJob.Status.BLOCKED, {
            "failure_class": "POLICY_OR_PRECONDITION", "reason": str(exc)[:400]}
    except (TimeoutError, subprocess.TimeoutExpired):
        status, result = AgentJob.Status.FAIL, {"failure_class": "TIMEOUT"}
    except Exception as exc:
        # A model/network error is never interpreted as a successful run.
        status, result = AgentJob.Status.FAIL, {
            "failure_class": "RUNTIME_OR_ENVIRONMENT", "error_type": type(exc).__name__}
    finally:
        AgentJob.objects.filter(pk=job.pk, status=AgentJob.Status.RUNNING).update(
            status=status, result=result, finished_at=timezone.now(),
        )
        record(job, "final_gate", status, {
            "failure_class": result.get("failure_class", ""),
            "candidate_only": bool(result.get("candidate_only", False)),
        })
    job.refresh_from_db()
    return job
