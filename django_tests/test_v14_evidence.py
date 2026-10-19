"""V1.4 tamper-resistant consistency rules (hashes are NOT a provider signature)."""
import copy
import hashlib
from types import SimpleNamespace

from django.test import SimpleTestCase

from agentforge_django.v11_benchmark import SCENARIOS, suite_fingerprint
from agentforge_django.v11_evaluation import summarize_suite
from agentforge_django.v12_reporting import attach_case_telemetry, attach_suite_metrics
from agentforge_django.v14_evidence import EvidenceRejected, verify_benchmark


def sample_report(*, real=False):
    cases = []
    kind = "REAL_DEEPSEEK" if real else "SCRIPTED_FAKE_AGENT"
    for s in SCENARIOS:
        row = {
            "case_id": s.identifier,
            "category": s.category,
            "status": "PASS",
            "baseline_failed": True,
            "baseline_tests_executed": True,
            "baseline_test_count": s.minimum_tests,
            "final_test_count": s.minimum_tests,
            "minimum_business_tests": s.minimum_tests,
            "test_suite_unchanged": True,
            "source_untouched": True,
            "independent_test_passed": True,
            "candidate_hash": "a" * 64,
            "original_source_sha256": hashlib.sha256(
                s.source.encode("utf-8")
            ).hexdigest(),
            "original_test_sha256": hashlib.sha256(
                s.tests.encode("utf-8")
            ).hexdigest(),
        }
        client = SimpleNamespace(
            calls=3,
            v12_role_trace=[
                {"role": role, "status": "SCHEMA_ACCEPTED"}
                for role in ("Planner", "Executor", "Reviewer")
            ],
            usage_reports=3,
            usage={"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
        )
        attach_case_telemetry(row, client, kind)
        if real:
            row["v13_trusted_broker_checked"] = True
        cases.append(row)
    report = summarize_suite(cases, manifest_sha256=suite_fingerprint(),
                             model_kind=kind)
    attach_suite_metrics(report)
    report["candidate_only"] = True
    report["source_or_test_files_committed"] = False
    return report


class EvidenceProtocolTests(SimpleTestCase):
    def test_scripted_three_case_report_is_consistent_but_not_real_model(self):
        report = sample_report()
        result = verify_benchmark(report, expected_model="SCRIPTED_FAKE_AGENT")
        self.assertTrue(result["consistent"])
        self.assertEqual(result["observed_cases_passed"], 3)
        self.assertFalse(result["independent_provider_identity_attested"])

    def test_scripted_report_cannot_be_relabelled_as_paid_deepseek(self):
        report = sample_report()
        report["model_kind"] = "REAL_DEEPSEEK"
        with self.assertRaises(EvidenceRejected):
            verify_benchmark(report, expected_model="REAL_DEEPSEEK")

    def test_mutated_suite_hash_and_tests_are_rejected(self):
        report = sample_report()
        report["suite_fingerprint"] = "b" * 64
        with self.assertRaises(EvidenceRejected):
            verify_benchmark(report, expected_model="SCRIPTED_FAKE_AGENT")
        report = sample_report()
        report["cases"][0]["final_test_count"] = 1
        with self.assertRaises(EvidenceRejected):
            verify_benchmark(report, expected_model="SCRIPTED_FAKE_AGENT")
        report = sample_report()
        report["cases"][1]["original_test_sha256"] = "0" * 64
        with self.assertRaises(EvidenceRejected):
            verify_benchmark(report, expected_model="SCRIPTED_FAKE_AGENT")

    def test_model_calls_and_token_forgery_rejected(self):
        report = sample_report()
        report["v12_metrics"]["total_model_requests_observed"] = 15
        with self.assertRaises(EvidenceRejected):
            verify_benchmark(report, expected_model="SCRIPTED_FAKE_AGENT")
        report = sample_report()
        report["cases"][0]["model_evidence"]["observed_tokens"] = {
            "prompt_tokens": 99,
        }
        with self.assertRaises(EvidenceRejected):
            verify_benchmark(report, expected_model="SCRIPTED_FAKE_AGENT")

    def test_real_mode_needs_individual_broker_provenance_for_every_success(self):
        report = sample_report(real=True)
        good = verify_benchmark(report, expected_model="REAL_DEEPSEEK")
        self.assertTrue(good["consistent"])
        self.assertFalse(good["independent_provider_identity_attested"])
        report["cases"][2]["v13_trusted_broker_checked"] = False
        with self.assertRaises(EvidenceRejected):
            verify_benchmark(report, expected_model="REAL_DEEPSEEK")

    def test_report_cannot_claim_production_release_or_false_aggregate(self):
        report = sample_report()
        report["production_release_authorized"] = True
        with self.assertRaises(EvidenceRejected):
            verify_benchmark(report, expected_model="SCRIPTED_FAKE_AGENT")
        report = sample_report()
        report["cases_passed"] = 2
        with self.assertRaises(EvidenceRejected):
            verify_benchmark(report, expected_model="SCRIPTED_FAKE_AGENT")

    def test_valid_failure_report_is_fail_not_three_of_three(self):
        report = sample_report()
        report["cases"][0]["status"] = "FAIL"
        report["cases_passed"] = 2
        report["overall"] = "FAIL"
        report["v12_metrics"]["case_pass_rate"]["passed"] = 2
        report["real_model_verified"] = False
        summary = verify_benchmark(report, expected_model="SCRIPTED_FAKE_AGENT")
        self.assertEqual(summary["observed_cases_passed"], 2)
        self.assertFalse(summary["pass_claim_supported_by_report"])
