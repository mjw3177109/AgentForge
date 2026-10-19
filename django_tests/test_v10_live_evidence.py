"""V1.0 real-model evidence remains classified separately from offline fixtures."""
import unittest

from django.test import SimpleTestCase

from agentforge.llm import LLMError
from agentforge_django.guard import BoundaryDenied
from agentforge_django.live_evidence import (
    classify_exception, failed_round, summarize_candidate,
)


def candidate(*, status="PROPOSED", reason=None, passed=True):
    return {
        "status": status, "reason": reason,
        "patch_sha256": "a" * 64,
        "production_release_authorized": False,
        "repair_attempts": 1,
        "budget": {"docker_verification_rounds": 2},
        "independent_verification": {
            "backend": "docker-offline",
            "passed": passed,
            "business_tests_executed": True,
            "checks": [{"success": True}, {"success": passed}],
        },
    }


class LiveEvidenceTests(SimpleTestCase):
    def test_valid_candidate_passes_only_with_two_checks(self):
        result = summarize_candidate(
            1, candidate(), calls=5, source_untouched=True
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failure_class"], None)
        self.assertFalse(result["production_release_authorized"])

    def test_no_business_checks_is_not_success(self):
        obj = candidate()
        obj["independent_verification"]["checks"] = [{"success": True}]
        result = summarize_candidate(1, obj, calls=5, source_untouched=True)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failure_class"], "MISSING_ACCEPTANCE_EVIDENCE")

    def test_review_refusal_classification(self):
        obj = candidate(status="BLOCKED", reason="REVIEW_NOT_APPROVED", passed=False)
        self.assertEqual(
            summarize_candidate(1, obj, calls=3, source_untouched=True)["failure_class"],
            "MODEL_REVIEW_REJECTED",
        )

    def test_failed_behavioral_validation_classification(self):
        obj = candidate(status="FAILED", passed=False)
        self.assertEqual(
            summarize_candidate(2, obj, calls=5, source_untouched=True)["failure_class"],
            "INDEPENDENT_BEHAVIORAL_TEST_FAILED",
        )

    def test_error_exception_never_serializes_secret(self):
        error = LLMError("API_TOKEN_SECRET_SHOULD_NOT_LEAK")
        result = failed_round(1, error)
        self.assertNotIn("API_TOKEN_SECRET_SHOULD_NOT_LEAK", str(result))
        self.assertEqual(result["failure_class"], "MODEL_TRANSPORT_OR_SCHEMA")
        self.assertEqual(classify_exception(BoundaryDenied("token")), "POLICY_OR_PRECONDITION")
