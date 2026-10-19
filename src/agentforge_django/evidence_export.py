"""Redacted, structured evidence export for explicitly authorized operators."""

from .audit import verify_chain


def export_summary(job):
    result = job.result if isinstance(job.result, dict) else {}
    verification = result.get("independent_verification", {})
    checks = verification.get("checks", []) if isinstance(verification, dict) else []
    if not isinstance(checks, list):
        checks = []
    # stdout/stderr/candidate_patch may contain secrets or personal data.
    # Export ONLY gate outcomes, never raw model output or source code.
    safe_checks = [
        {
            "success": bool(item.get("success")),
            "returncode": item.get("returncode"),
            "reason": item.get("reason", ""),
        } for item in checks if isinstance(item, dict)
    ]
    return {
        "schema": "agentforge.django.evidence.v1",
        "job_id": str(job.pk),
        "project_id": job.project_id,
        "mode": job.mode,
        "status": job.status,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "audit_hash_chain_valid": verify_chain(job),
        "events": [{
            "sequence": event.sequence,
            "phase": event.phase,
            "decision": event.decision,
            "event_hash": event.event_hash,
            "previous_hash": event.previous_hash,
        } for event in job.events.all()],
        "failure_class": result.get("failure_class", ""),
        "verification": {
            "passed": verification.get("passed") is True if isinstance(verification, dict) else False,
            "business_tests_executed": verification.get("business_tests_executed") is True
                if isinstance(verification, dict) else False,
            "checks": safe_checks,
        },
        "candidate_patch_sha256": result.get("patch_sha256"),
        "v06_budget": {
            name: result.get("budget", {}).get(name)
            for name in (
                "role_requests", "docker_verification_rounds", "max_role_requests",
                "max_docker_rounds", "billing_cost_known",
            )
            if isinstance(result.get("budget"), dict)
        },
        "v06_repair_attempts": result.get("repair_attempts") if
            type(result.get("repair_attempts")) is int else None,
        "production_release_authorized": False,
    }
