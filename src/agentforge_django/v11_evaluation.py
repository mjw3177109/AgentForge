"""Evidence grading. Fail closed on weak or ambiguous test count evidence."""
import re

from .live_evidence import failed_round, summarize_candidate


def ran_at_least_tests(checks, minimum):
    if not isinstance(checks, list) or len(checks) != 2:
        return False
    final = checks[-1]
    if not isinstance(final, dict) or final.get("success") is not True:
        return False
    # The test-count proof must come from trusted Docker result, never from LLM.
    text = str(final.get("stdout", "")) + "\n" + str(final.get("stderr", ""))
    matches = re.findall(r"\bRan\s+([0-9]+)\s+tests?\b", text)
    return any(int(count) >= minimum for count in matches)


def grade_case(scenario, candidate, *, calls, source_untouched,
               baseline_failed, baseline_tests_executed, final_tests_count):
    result = summarize_candidate(
        scenario.identifier, candidate, calls=calls,
        source_untouched=source_untouched,
    )
    result["case_id"] = scenario.identifier
    result["category"] = scenario.category
    result["minimum_business_tests"] = scenario.minimum_tests
    result["baseline_failed"] = baseline_failed is True
    result["baseline_tests_executed"] = baseline_tests_executed is True
    result["final_test_count"] = final_tests_count
    result["test_suite_unchanged"] = source_untouched is True
    if result["status"] == "PASS" and (
        not result["baseline_failed"] or not result["baseline_tests_executed"]
        or type(final_tests_count) is not int
        or final_tests_count < scenario.minimum_tests
    ):
        result["status"] = "FAIL"
        result["failure_class"] = "BENCHMARK_INCOMPLETE_OR_TEST_COVERAGE"
        result["candidate_hash"] = None
    return result


def test_count(evidence):
    if not isinstance(evidence, dict):
        return 0
    checks = evidence.get("checks", [])
    if not isinstance(checks, list):
        return 0
    counts = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        raw = str(check.get("stdout", "")) + "\n" + str(check.get("stderr", ""))
        counts.extend(int(x) for x in re.findall(r"\bRan\s+([0-9]+)\s+tests?\b", raw))
    return max(counts, default=0)


def summarize_suite(cases, *, manifest_sha256, model_kind):
    observed = [c.get("case_id") for c in cases]
    correct_order = observed == ["arith-001", "pricing-002", "access-003"]
    passes = sum(c.get("status") == "PASS" for c in cases)
    success = len(cases) == 3 and correct_order and passes == 3
    return {
        "schema": "agentforge.django.v11.benchmark.v1",
        "suite_fingerprint": manifest_sha256,
        "model_kind": model_kind,
        "case_count": 3,
        "cases_passed": passes,
        "overall": "PASS" if success else "FAIL",
        "cases": cases,
        "real_model_verified": model_kind == "REAL_DEEPSEEK" and success,
        "customer_projects_verified": False,
        "production_release_authorized": False,
    }
