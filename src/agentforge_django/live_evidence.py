"""Redacted, deterministic acceptance failure attribution (never source/log output)."""

from agentforge.llm import LLMError
from .guard import BoundaryDenied


def classify_exception(exc):
    """Do not serialize exception message: it can contain prompts or secrets."""
    if isinstance(exc, BoundaryDenied):
        return "POLICY_OR_PRECONDITION"
    if isinstance(exc, LLMError):
        return "MODEL_TRANSPORT_OR_SCHEMA"
    if isinstance(exc, TimeoutError):
        return "EXECUTION_TIMEOUT"
    if isinstance(exc, OSError):
        return "EXECUTION_ENVIRONMENT"
    return "UNEXPECTED_PIPELINE_EXCEPTION"


def failed_round(index, exc):
    return {
        "round": index,
        "status": "FAIL",
        "failure_class": classify_exception(exc),
        "error_type": type(exc).__name__[:64],
        "production_release_authorized": False,
    }


def summarize_candidate(index, candidate, *, calls, source_untouched):
    if not isinstance(candidate, dict):
        return {
            "round": index, "status": "FAIL",
            "failure_class": "INVALID_RESULT_STRUCTURE",
            "production_release_authorized": False,
        }
    evidence = candidate.get("independent_verification")
    if not isinstance(evidence, dict):
        evidence = {}
    checks = evidence.get("checks")
    valid_checks = (
        isinstance(checks, list)
        and len(checks) == 2
        and all(isinstance(c, dict) and c.get("success") is True for c in checks)
    )
    valid = (
        candidate.get("status") == "PROPOSED"
        and evidence.get("backend") == "docker-offline"
        and evidence.get("passed") is True
        and evidence.get("business_tests_executed") is True
        and valid_checks
        and source_untouched is True
        and type(calls) is int and 3 <= calls <= 5
        and candidate.get("production_release_authorized") is False
        and isinstance(candidate.get("patch_sha256"), str)
        and len(candidate.get("patch_sha256", "")) == 64
    )
    if valid:
        failure = None
    elif candidate.get("status") == "BLOCKED":
        failure = (
            "MODEL_REVIEW_REJECTED"
            if candidate.get("reason") == "REVIEW_NOT_APPROVED"
            else "POLICY_BLOCKED"
        )
    elif candidate.get("status") == "FAILED":
        checks = evidence.get("checks", [])
        if isinstance(checks, list) and any(
            isinstance(c, dict) and c.get("reason") in (
                "DOCKER_TIMEOUT", "DOCKER_LAUNCH_ERROR",
                "NO_POSITIVE_DJANGO_TEST_COUNT",
            ) for c in checks
        ):
            failure = "VERIFICATION_INFRASTRUCTURE"
        else:
            failure = "INDEPENDENT_BEHAVIORAL_TEST_FAILED"
    else:
        failure = "MISSING_ACCEPTANCE_EVIDENCE"
    return {
        "round": index,
        "status": "PASS" if valid else "FAIL",
        "failure_class": failure,
        "model_requests": calls if type(calls) is int else None,
        "repair_attempts": candidate.get("repair_attempts")
            if type(candidate.get("repair_attempts")) is int else None,
        "docker_verification_rounds": candidate.get("budget", {}).get(
            "docker_verification_rounds"
        ) if isinstance(candidate.get("budget"), dict) else None,
        "candidate_hash": candidate.get("patch_sha256")
            if valid else None,
        "independent_test_passed": evidence.get("passed") is True and valid_checks,
        "source_untouched": source_untouched is True,
        "production_release_authorized": False,
    }
