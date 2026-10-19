"""Strict consistency verifier for redacted three-case benchmark artifacts.

This verifies *internal report consistency*, not identity of the external
model/provider, Docker host integrity, or cryptographic attestation.
"""
import hashlib
import json
import re

from .v11_benchmark import SCENARIOS, suite_fingerprint
from .v15_consistency import check_model_telemetry, check_suite_telemetry


class EvidenceRejected(ValueError):
    pass


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _assert(condition, reason):
    if not condition:
        raise EvidenceRejected(reason)


def verify_benchmark(report, *, expected_model):
    """Fail closed on a success claim without full independent case evidence."""
    _assert(expected_model in ("SCRIPTED_FAKE_AGENT", "REAL_DEEPSEEK"),
            "Invalid expected model")
    _assert(isinstance(report, dict), "Benchmark must be a JSON object")
    _assert(report.get("schema") == "agentforge.django.v11.benchmark.v1",
            "Unexpected benchmark schema")
    _assert(report.get("model_kind") == expected_model,
            "Model provenance label does not match expected mode")
    _assert(report.get("suite_fingerprint") == suite_fingerprint(),
            "Benchmark fixture manifest changed")
    _assert(report.get("case_count") == 3, "Benchmark case count mismatch")
    _assert(report.get("production_release_authorized") is False
            and report.get("customer_projects_verified") is False
            and report.get("candidate_only") is True
            and report.get("source_or_test_files_committed") is False,
            "Report must explicitly disallow real project/deployment changes")

    cases = report.get("cases")
    _assert(isinstance(cases, list) and len(cases) == 3,
            "Three distinct cases required")
    _assert([case.get("case_id") for case in cases if isinstance(case, dict)]
            == [s.identifier for s in SCENARIOS], "Case order/IDs mismatch")
    passes = 0
    model_requests = 0
    for case, scenario in zip(cases, SCENARIOS):
        _assert(isinstance(case, dict), "Malformed case record")
        _assert(case.get("status") in ("PASS", "FAIL", "BLOCKED"),
                "Unrecognized case result")
        evidence = case.get("model_evidence")
        _assert(isinstance(evidence, dict), "Model evidence missing")
        _assert(evidence.get("provenance") == expected_model,
                "Case model provenance mismatch")
        trace = evidence.get("role_trace")
        _assert(isinstance(trace, list) and len(trace) <= 5,
                "Model role trace invalid")
        for event in trace:
            _assert(isinstance(event, dict) and event.get("role") in (
                "Planner", "Executor", "Reviewer", "Fixer"
            ) and event.get("status") in (
                "SCHEMA_ACCEPTED", "ATTEMPTED", "ERROR"
            ), "Model role trace invalid")
        calls = evidence.get("attempted_requests")
        _assert(calls is None or type(calls) is int and 0 <= calls <= 5,
                "Invalid model call count")
        model_requests += calls or 0
        if expected_model == "SCRIPTED_FAKE_AGENT":
            _assert(evidence.get("usage_coverage") == "NOT_APPLICABLE"
                    and evidence.get("observed_tokens") is None
                    and evidence.get("provider_usage_reports") is None,
                    "Scripted model must not claim provider tokens")
        else:
            _assert(evidence.get("usage_coverage") in (
                "COMPLETE", "PARTIAL", "UNKNOWN"
            ), "Real model token coverage invalid")
            _assert(case.get("v13_trusted_broker_checked") is not False
                    or case.get("status") != "PASS",
                    "Passing real case lacks trusted Broker")

        check_model_telemetry(case, expected_model, _assert)
        if case["status"] != "PASS":
            continue
        passes += 1
        _assert(case.get("baseline_failed") is True
                and case.get("baseline_tests_executed") is True
                and case.get("source_untouched") is True
                and case.get("test_suite_unchanged") is True,
                "Missing failing-baseline or immutable source evidence")
        _assert(case.get("category") == scenario.category
                and case.get("minimum_business_tests") == scenario.minimum_tests,
                "Scenario category/test threshold mismatch")
        _assert(type(case.get("baseline_test_count")) is int
                and case["baseline_test_count"] >= scenario.minimum_tests
                and type(case.get("final_test_count")) is int
                and case["final_test_count"] >= scenario.minimum_tests,
                "Independent Django test-count requirement not met")
        _assert(case.get("independent_test_passed") is True
                and case.get("verification_kind") == "OFFLINE_DOCKER",
                "Passing case must have offline Docker acceptance evidence")
        _assert(_sha(case.get("candidate_hash")),
                "Passing case patch digest absent")
        _assert(case.get("original_source_sha256")
                == hashlib.sha256(scenario.source.encode("utf-8")).hexdigest()
                and case.get("original_test_sha256")
                == hashlib.sha256(scenario.tests.encode("utf-8")).hexdigest(),
                "Original source/test digest mismatch")
        _assert(type(calls) is int and 3 <= calls <= 5,
                "Passing candidate outside model-call budget")
        _assert(sum(event.get("status") == "SCHEMA_ACCEPTED"
                    for event in trace) >= 3,
                "Passing case lacks Planner/Executor/Reviewer schema evidence")
        if expected_model == "REAL_DEEPSEEK":
            _assert(case.get("v13_trusted_broker_checked") is True,
                    "Passing real case has no runtime Broker check")

    success = passes == 3
    _assert(report.get("cases_passed") == passes,
            "Aggregated passed cases mismatch")
    _assert(report.get("overall") == ("PASS" if success else "FAIL"),
            "Suite status is inconsistent with case results")
    _assert(report.get("real_model_verified") is (
        expected_model == "REAL_DEEPSEEK" and success
    ), "Real-model claim invalid")
    metrics = report.get("v12_metrics")
    _assert(isinstance(metrics, dict), "V1.2 metrics missing")
    rate = metrics.get("case_pass_rate")
    _assert(isinstance(rate, dict) and rate.get("passed") == passes
            and rate.get("total") == 3, "Case pass-rate inconsistent")
    _assert(metrics.get("total_model_requests_observed") == model_requests,
            "Model call-count aggregation inconsistent")
    _assert(metrics.get("model_cost_is_verified") is False
            and metrics.get("observed_usd_spend") is None,
            "Provider billing has not been independently verified")
    if expected_model == "SCRIPTED_FAKE_AGENT":
        _assert(metrics.get("provider_usage_coverage") == "NOT_APPLICABLE"
                and metrics.get("observed_tokens") is None,
                "Synthetic suite cannot claim model tokens")
    check_suite_telemetry(report, expected_model, _assert)
    return {
        "consistent": True,
        "expected_model_kind": expected_model,
        "observed_cases_passed": passes,
        "benchmark_case_count": 3,
        "pass_claim_supported_by_report": success,
        "independent_provider_identity_attested": False,
        "real_customer_project_verified": False,
        "production_release_authorized": False,
        "note": "Internal consistency only; independently check CI run and provider records.",
    }


def digest_report_bytes(raw):
    return hashlib.sha256(raw).hexdigest()
