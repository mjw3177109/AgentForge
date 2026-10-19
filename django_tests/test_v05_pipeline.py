"""V0.5 negative policy tests and offline stand-in actors. NO paid model calls."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from agentforge_django.guard import BoundaryDenied
from agentforge_django.v05_broker import BoundedDeepSeek, create_v05_broker
from agentforge_django.v05_coding import produce_candidate
from agentforge_django.v05_fixture import REQUEST, ScriptedFakeAgent, make_fixture


def valid_docker_pass():
    return {
        "backend": "docker-offline", "passed": True,
        "business_tests_executed": True,
        "checks": [
            {"success": True, "returncode": 0},
            {"success": True, "returncode": 0},
        ],
    }


class CodingPipelineTests(SimpleTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="af-v05-policy-")
        self.addCleanup(temp.cleanup)
        self.root = make_fixture(Path(temp.name) / "sample")

    def test_pipeline_requires_real_independent_validator(self):
        broker = ScriptedFakeAgent()
        with patch(
            "agentforge_django.v05_coding.isolated_verification",
            return_value=valid_docker_pass(),
        ) as validator:
            outcome = produce_candidate(broker, self.root, REQUEST, ["app/**"])
        self.assertEqual(outcome["status"], "PROPOSED")
        self.assertEqual(outcome["review_decision"], "APPROVE")
        self.assertEqual(outcome["model_calls"], 3)
        self.assertTrue(outcome["independent_verification"]["passed"])
        self.assertEqual(validator.call_count, 1)
        self.assertIn("return a - b", (self.root / "app/views.py").read_text("utf-8"))
        self.assertFalse(outcome["production_release_authorized"])

    def test_reviewer_rejects_and_never_runs_generated_code(self):
        with patch("agentforge_django.v05_coding.isolated_verification") as validator:
            result = produce_candidate(
                ScriptedFakeAgent(decision="REQUEST_CHANGES"),
                self.root, REQUEST, ["app/**"],
            )
        self.assertEqual(result["status"], "BLOCKED")
        validator.assert_not_called()

    def test_scope_escape_rejected_before_executor(self):
        with self.assertRaises(BoundaryDenied), patch(
            "agentforge_django.v05_coding.isolated_verification"
        ) as validator:
            produce_candidate(
                ScriptedFakeAgent(path="demo/settings.py"),
                self.root, REQUEST, ["app/**"],
            )
        validator.assert_not_called()

    def test_test_module_inside_approved_app_scope_is_protected(self):
        from agentforge_django.v05_coding import _safe_python
        with self.assertRaises(BoundaryDenied):
            _safe_python(self.root, "app/tests.py", ["app/**"])

    def test_business_failure_cannot_be_proposed(self):
        failed = {
            "backend": "docker-offline", "passed": False,
            "business_tests_executed": True,
            "checks": [{"success": False, "reason": "ASSERTION_FAILED"}],
        }
        with patch("agentforge_django.v05_coding.isolated_verification", return_value=failed):
            outcome = produce_candidate(
                ScriptedFakeAgent(), self.root, REQUEST, ["app/**"],
            )
        self.assertEqual(outcome["status"], "FAILED")
        self.assertIsNone(outcome["candidate_patch"])

    def test_no_source_transfer_opt_in_blocks_broker(self):
        with override_settings(AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=False):
            with self.assertRaises(BoundaryDenied):
                create_v05_broker()

    def test_model_calls_are_hard_bounded(self):
        broker = BoundedDeepSeek(
            base_url="https://api.deepseek.com", api_key="unused-fake-token",
            model="deepseek-chat", max_requests=0,
        )
        with self.assertRaises(BoundaryDenied):
            broker._request("system", "user")
        self.assertEqual(broker.calls, 0)

    def test_unapproved_full_file_glob_cannot_apply(self):
        with self.assertRaises(BoundaryDenied):
            produce_candidate(
                ScriptedFakeAgent(), self.root, REQUEST, ["**/*"],
            )

    def test_zero_request_denied(self):
        with self.assertRaises(BoundaryDenied):
            produce_candidate(
                ScriptedFakeAgent(), self.root, "", ["app/**"],
            )
