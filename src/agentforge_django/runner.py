"""Synchronous job worker. Execute with management command, never an HTTP handler."""

import hashlib
import uuid
import os
from unittest.mock import patch
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction, connection
from django.utils import timezone

from .audit import record
from .approvals import approval_digests
from .guard import (
    BoundaryDenied, checked_root, private_environment, scope_within, scoped_file, validate_write_scopes,
)
from .inspection import inspect_python, sanitized_manifest
from .models import AgentJob, JobLease
from .lease_heartbeat import LeaseHeartbeat, lease_owned
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
    if getattr(settings, "AGENTFORGE_V05_ISOLATED_AUTONOMOUS", False):
        from .v05_coding import run_approved_v05
        outcome = run_approved_v05(job, root)
        decision = outcome.get("status")
        record(job, "v05_review", outcome.get("review_decision", "NOT_RUN"), {
            "model_calls": outcome.get("model_calls"),
            "source_file_count": len(outcome.get("source_files", [])),
        })
        verification = outcome.get("independent_verification", {})
        record(job, "v05_validator", "PASS" if verification.get("passed") else "NOT_PASS", {
            "backend": verification.get("backend", "NOT_RUN"),
            "checks": len(verification.get("checks", [])),
        })
        if decision == "PROPOSED":
            return AgentJob.Status.PROPOSED, outcome
        if decision == "FAILED":
            return AgentJob.Status.FAIL, outcome
        return AgentJob.Status.BLOCKED, outcome
    # Legacy Core V2.0 executes agent-generated verification commands in host
    # subprocesses. It is deliberately OFF by default in V0.4. Docker VERIFY
    # is safe to use independently, but cannot secure the earlier coding stage.
    if not (
        getattr(settings, "AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS", False)
        and getattr(settings, "AGENTFORGE_VERIFICATION_BACKEND", "docker") == "local"
        and getattr(settings, "AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY", False)
    ):
        raise BoundaryDenied(
            "AUTONOMOUS requires a separately isolated coding executor; "
            "legacy host execution is disabled by default"
        )
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
    expected_request, expected_config = approval_digests(job)
    if approval.request_sha256 != expected_request or approval.configuration_sha256 != expected_config:
        raise BoundaryDenied("Approved request or project settings changed; new approval required")
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
        llm_client = ExternalLLMSettings.from_env().client()
        pipeline = AutonomousDevelopmentPipeline(
            client=llm_client,
            repo_root=sandbox,
            profiles=loaded.profiles,
            allowed_verification_executables=loaded.allowed_executables,
            max_coding_attempts=2,
            max_review_rounds=2,
        )
        # A single-job worker must not pass DeepSeek/API/database credentials to
        # generated code or the core's verification subprocesses.
        # This is defense in depth, not a substitute for an isolated OS worker.
        with patch.dict(os.environ, private_environment(), clear=True):
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
    """Claim one project-wide lease before RUNNING; never execute concurrent project jobs."""
    job = AgentJob.objects.select_related("project").get(pk=job_id)
    if job.status != AgentJob.Status.PENDING:
        return job
    if getattr(settings, "AGENTFORGE_V09_HEARTBEAT_ENABLED", False) and connection.vendor != "postgresql":
        raise BoundaryDenied("V0.9 trusted worker heartbeat requires PostgreSQL")
    token = uuid.uuid4()
    try:
        with transaction.atomic():
            JobLease.objects.create(
                project=job.project, job=job, owner_token=token,
                heartbeat_enabled=bool(
                    getattr(settings, "AGENTFORGE_V09_HEARTBEAT_ENABLED", False)
                ),
            )
    except IntegrityError:
        # An existing lease means another worker owns this project.
        # Leave the job pending; never silently steal a lease.
        return job
    try:
        claimed = AgentJob.objects.filter(
            pk=job.pk, status=AgentJob.Status.PENDING
        ).update(status=AgentJob.Status.RUNNING, started_at=timezone.now())
        if not claimed:
            job.refresh_from_db()
            return job
        heartbeat = LeaseHeartbeat(
            job_id=job.pk, project_id=job.project_id, token=token,
        )
        try:
            heartbeat.start()
        except Exception as exc:
            AgentJob.objects.filter(pk=job.pk, status=AgentJob.Status.RUNNING).update(
                status=AgentJob.Status.BLOCKED,
                result={"failure_class": "HEARTBEAT_START_FAILED",
                        "error_type": type(exc).__name__},
                finished_at=timezone.now(),
            )
            record(job, "final_gate", "BLOCKED", {
                "failure_class": "HEARTBEAT_START_FAILED",
            })
            job.refresh_from_db()
            return job
        try:
            return _run_claimed_job(job, token=token, heartbeat=heartbeat)
        finally:
            heartbeat.stop()
    finally:
        JobLease.objects.filter(project=job.project, owner_token=token).delete()


def _run_claimed_job(job, *, token=None, heartbeat=None):
    """Finalize status and audit even if the execution fails."""
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
            if not job.project.run_business_tests:
                raise BoundaryDenied("Business tests are disabled; VERIFY cannot prove behavior")
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
        if heartbeat is not None:
            heartbeat.stop()
            if not isinstance(result, dict):
                result = {"failure_class": "INVALID_EXECUTION_RESULT"}
            result["worker_heartbeat"] = {
                "enabled": bool(getattr(settings, "AGENTFORGE_V09_HEARTBEAT_ENABLED", False)),
                "beats": heartbeat.beats,
                "ownership_preserved": not heartbeat.lost.is_set(),
            }
        if token is not None and (
            (heartbeat is not None and heartbeat.lost.is_set())
            or not lease_owned(project_id=job.project_id, job_id=job.pk, token=token)
        ):
            status, result = AgentJob.Status.BLOCKED, {
                "failure_class": "WORKER_LEASE_LOST",
                "reason": "Worker ownership or heartbeat lost; never publish candidate",
            }
        finalized = AgentJob.objects.filter(
            pk=job.pk, status=AgentJob.Status.RUNNING
        ).update(status=status, result=result, finished_at=timezone.now())
        # Another operator may have explicitly recovered the worker meanwhile.
        # Never turn that recovered BLOCKED job back into PASS/PROPOSED.
        if finalized:
            record(job, "final_gate", status, {
                "failure_class": result.get("failure_class", ""),
                "candidate_only": bool(result.get("candidate_only", False)),
            })
        else:
            # A recovered worker must not append new events after the operator
            # has fenced its result. The recovery event is the terminal evidence.
            pass
    job.refresh_from_db()
    return job
