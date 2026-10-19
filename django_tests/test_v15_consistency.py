"""V1.5 adversarial report mutation tests — no DeepSeek calls, no Docker."""
import copy

from django.test import SimpleTestCase

from django_tests.test_v14_evidence import sample_report
from agentforge_django.v14_evidence import EvidenceRejected, verify_benchmark
from agentforge_django.v12_reporting import attach_suite_metrics


def validated(report, *, real=False):
    return verify_benchmark(
        report, expected_model="REAL_DEEPSEEK" if real else "SCRIPTED_FAKE_AGENT"
    )


class V15CoherenceTests(SimpleTestCase):
    def test_v14_legitimate_fake_and_real_reports_remain_compatible(self):
        self.assertEqual(validated(sample_report())["observed_cases_passed"], 3)
        self.assertEqual(validated(sample_report(real=True), real=True)["observed_cases_passed"], 3)

    def test_repeated_planner_cannot_replace_executor_and_reviewer(self):
        report = sample_report()
        trace = report["cases"][0]["model_evidence"]["role_trace"]
        for item in trace:
            item["role"] = "Planner"
        report["v12_metrics"]["role_schema_acceptances"] = {
            "Planner": 5, "Executor": 2, "Reviewer": 2, "Fixer": 0
        }
        with self.assertRaises(EvidenceRejected):
            validated(report)

    def test_success_cannot_skip_second_reviewer_after_fixer(self):
        report = sample_report()
        case = report["cases"][0]
        case["repair_attempts"] = 1
        case["repair_path"] = "ONE_REPAIR"
        case["docker_verification_rounds"] = 2
        # Trace still only contains the initial three successful calls.
        report["v12_metrics"]["cases_passing_after_one_repair"] = 1
        with self.assertRaises(EvidenceRejected):
            validated(report)

    def test_missing_schema_success_is_not_three_of_three(self):
        report = sample_report()
        case = report["cases"][1]
        case["model_evidence"]["role_trace"][2]["status"] = "ERROR"
        case["role_schema_accepted"] = 2
        report["v12_metrics"]["role_schema_acceptances"]["Reviewer"] = 2
        with self.assertRaises(EvidenceRejected):
            validated(report)

    def test_wrong_docker_round_count_rejected(self):
        report = sample_report()
        report["cases"][0]["docker_verification_rounds"] = 2
        with self.assertRaises(EvidenceRejected):
            validated(report)

    def test_total_role_requests_not_forged_even_if_suite_total_altered(self):
        report = sample_report()
        report["cases"][0]["model_evidence"]["attempted_requests"] = 4
        report["v12_metrics"]["total_model_requests_observed"] = 10
        with self.assertRaises(EvidenceRejected):
            validated(report)

    def test_real_complete_usage_cannot_claim_missing_token_reports(self):
        report = sample_report(real=True)
        case = report["cases"][0]
        case["model_evidence"]["provider_usage_reports"] = 2
        report["v12_metrics"]["provider_token_reports_received"] = 8
        with self.assertRaises(EvidenceRejected):
            validated(report, real=True)

    def test_real_suite_token_sum_must_match_cases(self):
        report = sample_report(real=True)
        report["v12_metrics"]["observed_tokens"]["total_tokens"] += 100
        with self.assertRaises(EvidenceRejected):
            validated(report, real=True)

    def test_real_token_breakdown_cannot_be_negative_or_missing(self):
        report = sample_report(real=True)
        report["cases"][0]["model_evidence"]["observed_tokens"]["prompt_tokens"] = -5
        with self.assertRaises(EvidenceRejected):
            validated(report, real=True)
        report = sample_report(real=True)
        del report["cases"][0]["model_evidence"]["observed_tokens"]["total_tokens"]
        with self.assertRaises(EvidenceRejected):
            validated(report, real=True)

    def test_real_unknown_usage_requires_no_observed_tokens(self):
        report = sample_report(real=True)
        case = report["cases"][0]
        case["model_evidence"]["usage_coverage"] = "UNKNOWN"
        case["model_evidence"]["provider_usage_reports"] = 0
        # A fake/non-reported token total cannot linger in the per-case report.
        with self.assertRaises(EvidenceRejected):
            validated(report, real=True)

    def test_fake_suite_cannot_claim_provider_token_report_count(self):
        report = sample_report()
        report["v12_metrics"]["provider_token_reports_received"] = 7
        with self.assertRaises(EvidenceRejected):
            validated(report)

    def test_totals_and_repair_success_metric_must_match_case_records(self):
        report = sample_report()
        report["v12_metrics"]["cases_passing_after_one_repair"] = 3
        with self.assertRaises(EvidenceRejected):
            validated(report)
        report = sample_report()
        report["v12_metrics"]["role_schema_acceptances"]["Executor"] += 1
        with self.assertRaises(EvidenceRejected):
            validated(report)

    def test_real_usage_partial_legitimate_case_and_suite_report(self):
        report = sample_report(real=True)
        first = report["cases"][0]["model_evidence"]
        first["usage_coverage"] = "PARTIAL"
        first["provider_usage_reports"] = 2
        attach_suite_metrics(report)
        self.assertEqual(validated(report, real=True)["observed_cases_passed"], 3)

    def test_three_cases_with_one_successful_repair_still_valid(self):
        report = sample_report()
        case = report["cases"][0]
        case["repair_attempts"] = 1
        case["repair_path"] = "ONE_REPAIR"
        case["docker_verification_rounds"] = 2
        case["model_evidence"]["attempted_requests"] = 5
        case["model_evidence"]["role_trace"].extend([
            {"role": "Fixer", "status": "SCHEMA_ACCEPTED"},
            {"role": "Reviewer", "status": "SCHEMA_ACCEPTED"},
        ])
        case["role_schema_accepted"] = 5
        attach_suite_metrics(report)
        self.assertEqual(validated(report)["observed_cases_passed"], 3)
