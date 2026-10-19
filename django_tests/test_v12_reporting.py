"""V1.2 simulated/real reporting never confuses missing API usage with zero cost."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from agentforge.llm import LLMError
from agentforge_django.v06_repair import Budget
from agentforge_django.v05_coding import CodingPlan
from agentforge_django.v12_reporting import (
    attach_case_telemetry, attach_suite_metrics, model_evidence,
)


class ReportingTests(SimpleTestCase):
    def test_simulated_model_cannot_claim_provider_usage(self):
        agent = SimpleNamespace(
            calls=5, usage_reports=5,
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            v12_role_trace=[{"role": "Planner", "status": "SCHEMA_ACCEPTED"}],
        )
        result = model_evidence(agent, "SCRIPTED_FAKE_AGENT")
        self.assertEqual(result["usage_coverage"], "NOT_APPLICABLE")
        self.assertIsNone(result["observed_tokens"])
        self.assertIsNone(result["provider_usage_reports"])

    def test_real_model_partial_reports_and_missing_data(self):
        agent = SimpleNamespace(
            calls=5, usage_reports=3,
            usage={"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000},
        )
        result = model_evidence(agent, "REAL_DEEPSEEK")
        self.assertEqual(result["usage_coverage"], "PARTIAL")
        self.assertEqual(result["observed_tokens"]["total_tokens"], 1000)
        self.assertIsNone(result["spend_usd"])
        agent.usage_reports = 0
        result = model_evidence(agent, "REAL_DEEPSEEK")
        self.assertEqual(result["usage_coverage"], "UNKNOWN")
        self.assertIsNone(result["observed_tokens"])

    def test_complete_real_coverage_rollup(self):
        cases = []
        for index, cid in enumerate(("arith-001", "pricing-002", "access-003")):
            case = {"case_id": cid, "status": "PASS",
                    "repair_attempts": index % 2, "independent_test_passed": True}
            calls = index + 3
            client = SimpleNamespace(
                calls=calls, usage_reports=calls,
                usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                v12_role_trace=[{"role": "Planner", "status": "SCHEMA_ACCEPTED"}],
            )
            attach_case_telemetry(case, client, "REAL_DEEPSEEK")
            cases.append(case)
        summary = {"model_kind": "REAL_DEEPSEEK", "cases": cases,
                   "case_count": 3, "cases_passed": 3}
        attach_suite_metrics(summary)
        metrics = summary["v12_metrics"]
        self.assertEqual(metrics["provider_usage_coverage"], "COMPLETE")
        self.assertEqual(metrics["observed_tokens"]["total_tokens"], 360)
        self.assertEqual(metrics["total_model_requests_observed"], 12)
        self.assertEqual(metrics["provider_token_reports_received"], 12)
        self.assertEqual(metrics["cases_passing_after_one_repair"], 1)
        self.assertFalse(metrics["model_cost_is_verified"])

    def test_exception_trace_does_not_leak_prompt_or_message(self):
        client = SimpleNamespace(calls=0)
        with patch("agentforge_django.v06_repair._call",
                   side_effect=LLMError("SECRET_KEY_AND_PROMPT")):
            with self.assertRaises(LLMError):
                Budget().call(client, "Planner", "SECRET_KEY_AND_PROMPT", CodingPlan)
        self.assertEqual(client.v12_role_trace, [
            {"role": "Planner", "status": "ERROR"}
        ])
        self.assertNotIn("SECRET_KEY", str(client.v12_role_trace))

    def test_untrusted_trace_fields_are_removed(self):
        client = SimpleNamespace(
            calls=1,
            v12_role_trace=[
                {"role": "Planner", "status": "SCHEMA_ACCEPTED", "prompt": "SECRET"},
                {"role": "unauthorized", "status": "SCHEMA_ACCEPTED"},
            ],
        )
        report = model_evidence(client, "REAL_DEEPSEEK")
        self.assertEqual(report["role_trace"], [
            {"role": "Planner", "status": "SCHEMA_ACCEPTED"}
        ])
        self.assertNotIn("SECRET", str(report))
