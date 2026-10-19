"""V1.3 safeguards: simulated clients cannot impersonate real DeepSeek.

No real API calls or network traffic in these tests.
"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from agentforge_django.guard import BoundaryDenied
from agentforge_django.v05_broker import BoundedDeepSeek
from agentforge_django.v11_runner import run_three_case_suite
from agentforge_django.v13_checkpoint import write_checkpoint
from agentforge_django.v13_provenance import assert_real_client


def real_broker():
    return BoundedDeepSeek(
        api_key="fixture-only-do-not-send", base_url="https://api.deepseek.com",
        model="deepseek-chat", max_requests=5,
    )


def failed_docker_baseline(*args, **kwargs):
    return {
        "backend": "docker-offline", "passed": False,
        "business_tests_executed": True,
        "checks": [
            {"success": True, "returncode": 0},
            {"success": False, "returncode": 1, "stdout": "Ran 8 tests in 0.002s"},
        ],
    }


class V13ProvenanceTests(SimpleTestCase):
    def test_scripted_mock_is_rejected_as_real(self):
        with self.assertRaises(BoundaryDenied):
            assert_real_client(SimpleNamespace(calls=0, remaining=5))

    def test_real_broker_requires_official_https_and_fresh_five_call_budget(self):
        assert_real_client(real_broker())
        broker = real_broker()
        broker.remaining = 4
        with self.assertRaises(BoundaryDenied):
            assert_real_client(broker)
        broker = real_broker()
        broker.model = "other-model"
        with self.assertRaises(BoundaryDenied):
            assert_real_client(broker)

    def test_real_runner_requires_three_docker_preflights_before_any_paid_broker(self):
        factory = Mock()
        invalid = {**failed_docker_baseline(), "passed": True}
        with patch("agentforge_django.v11_runner.docker_verification", return_value=invalid) as docker:
            with self.assertRaisesRegex(RuntimeError, "NO_PAID_CALLS"):
                run_three_case_suite(factory, model_kind="REAL_DEEPSEEK")
        self.assertEqual(docker.call_count, 3)
        factory.assert_not_called()

    def test_real_label_cannot_promote_scripted_client(self):
        from agentforge_django.v11_fake_agent import FakeScenarioAgent
        with patch("agentforge_django.v11_runner.docker_verification",
                   side_effect=failed_docker_baseline):
            report = run_three_case_suite(
                lambda scenario: FakeScenarioAgent(scenario),
                model_kind="REAL_DEEPSEEK",
            )
        self.assertEqual(report["overall"], "FAIL")
        self.assertFalse(report["real_model_verified"])
        self.assertEqual(report["cases_passed"], 0)
        self.assertTrue(all(
            case["v13_trusted_broker_checked"] is False
            for case in report["cases"]
        ))
        self.assertEqual(report["failure_class"], "UNTRUSTED_REAL_MODEL_PROVENANCE")

    def test_checkpoint_is_partial_and_contains_no_untrusted_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "checkpoint.json"
            original = write_checkpoint(
                file,
                cases=[
                    {"case_id": "arith-001", "status": "PASS",
                     "candidate_patch": "SECRET_SENTINEL_DO_NOT_INCLUDE",
                     "model_evidence": {"attempted_requests": 3},
                     "failure_class": "VERIFICATION_INFRASTRUCTURE"},
                ],
                manifest="fixture-test-fingerprint",
                model_kind="REAL_DEEPSEEK",
            )
            loaded = json.loads(file.read_text("utf-8"))
            self.assertEqual(original, loaded)
            self.assertEqual(loaded["phase"], "INCOMPLETE_UNTIL_FINAL_REPORT")
            self.assertFalse(loaded["real_model_verified"])
            self.assertNotIn("SECRET_SENTINEL", file.read_text("utf-8"))
            self.assertEqual(loaded["cases_finished"], 1)
