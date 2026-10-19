"""Fail-closed candidate handoff. Never apply, merge or deploy a patch."""
import hashlib
import re

from .approvals import approval_digests
from .audit import verify_chain
from .guard import BoundaryDenied, safe_relative, validate_write_scopes, scope_within
from .models import AgentJob, MutationApproval


def verified_patch(job):
    if job.mode != AgentJob.Mode.AUTONOMOUS or job.status != AgentJob.Status.PROPOSED:
        raise BoundaryDenied("Only completed autonomous candidate jobs are exportable")
    if not verify_chain(job):
        raise BoundaryDenied("Audit chain verification failed")
    result = job.result if isinstance(job.result, dict) else {}
    patch = result.get("candidate_patch")
    digest = result.get("patch_sha256")
    if not isinstance(patch, str) or not patch or len(patch.encode("utf-8")) > 100000:
        raise BoundaryDenied("Candidate patch missing or exceeds limit")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BoundaryDenied("Candidate patch checksum missing")
    if hashlib.sha256(patch.encode("utf-8")).hexdigest() != digest:
        raise BoundaryDenied("Candidate patch checksum mismatch")
    verification = result.get("independent_verification")
    if not isinstance(verification, dict):
        raise BoundaryDenied("Independent validation evidence missing")
    checks = verification.get("checks")
    if not (
        verification.get("backend") == "docker-offline"
        and verification.get("passed") is True
        and verification.get("business_tests_executed") is True
        and isinstance(checks, list) and len(checks) == 2
        and all(isinstance(x, dict) and x.get("success") is True for x in checks)
        and result.get("production_release_authorized") is False
    ):
        raise BoundaryDenied("Docker check/test gate not satisfied")

    try:
        approval = job.approval
    except MutationApproval.DoesNotExist as exc:
        raise BoundaryDenied("Candidate has no original human approval") from exc
    approver = approval.approved_by
    if not (approver.is_active and approver.is_staff and approver.is_superuser):
        raise BoundaryDenied("Approval actor is no longer authorized")
    if (approval.request_sha256, approval.configuration_sha256) != approval_digests(job):
        raise BoundaryDenied("Job or policy changed after human approval")
    ceilings = validate_write_scopes(approval.approved_scopes)
    if ceilings != validate_write_scopes(job.project.write_scopes):
        raise BoundaryDenied("Project write scope changed")

    # Diff headers MUST be exactly the model-validated existing .py paths.
    sources = result.get("source_files")
    if not isinstance(sources, list) or not sources or len(sources) > 3:
        raise BoundaryDenied("Approved source manifest missing")
    if len(sources) != len(set(sources)):
        raise BoundaryDenied("Duplicate paths in manifest")
    for rel in sources:
        if not isinstance(rel, str):
            raise BoundaryDenied("Invalid candidate source path")
        safe_relative(rel)
        if not rel.endswith(".py") or not any(scope_within(rel, [scope]) for scope in ceilings):
            raise BoundaryDenied("Candidate manifest exceeds approved scope")

    from_paths, to_paths = [], []
    for line in patch.splitlines():
        if line.startswith("--- "):
            from_paths.append(line[4:])
        if line.startswith("+++ "):
            to_paths.append(line[4:])
    if from_paths != ["a/" + name for name in sorted(sources)] or (
        to_paths != ["b/" + name for name in sorted(sources)]
    ):
        raise BoundaryDenied("Patch headers do not match approved manifest")
    return patch
