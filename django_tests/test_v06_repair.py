"""V0.6 offline gate tests; model outputs and Docker outcomes are mocked here."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from agentforge_django.guard import BoundaryDenied
from agentforge_django.v05_fixture import REQUEST, make_fixture
from agentforge_django.v06_fixture import FakeRepairModel
from agentforge_django.v06_repair import Budget, produce_candidate_v06


def verify(ok, reason="", secret=False):
    return {
        "backend": "docker-offline",
        "passed": ok,
        "business_tests_executed": True,
        "checks": [
            {"success": True, "returncode": 0, "stdout": "SENSITIVE_TOKEN"},
            {"success": ok, "returncode": 0 if ok else 1,
             "reason": reason, "stderr": "SENSITIVE_TOKEN" if secret else ""},
        ],
    }


class RepairTests(SimpleTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="af-v06-tests-")
        self.addCleanup(temp.cleanup)
        self.root = make_fixture(Path(temp.name) / "source")

    def test_one_repair_then_two_independent_validations(self):
        client = FakeRepairModel()
        with patch("agentforge_django.v06_repair.docker_verification",
                   side_effect=[verify(False), verify(True)]) as docker:
            result = produce_candidate_v06(client, self.root, REQUEST, ["app/**"])
        self.assertEqual(result["status"], "PROPOSED")
        self.assertEqual(result["repair_attempts"], 1)
        self.assertEqual(client.calls, 5)
        self.assertEqual(result["budget"]["role_requests"], 5)
        self.assertEqual(result["budget"]["docker_verification_rounds"], 2)
        self.assertEqual(docker.call_count, 2)
        self.assertFalse(result["production_release_authorized"])
        self.assertIn("return a - b", (self.root / "app/views.py").read_text("utf-8"))

    def test_review_reject_on_second_attempt_never_runs_second_validator(self):
        fake = FakeRepairModel(second_review="BLOCKED")
        with patch("agentforge_django.v06_repair.docker_verification",
                   side_effect=[verify(False), verify(True)]) as docker:
            result = produce_candidate_v06(fake, self.root, REQUEST, ["app/**"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["review_decision"], "BLOCKED")
        self.assertEqual(docker.call_count, 1)
        self.assertIsNone(result.get("candidate_patch"))

    def test_infrastructure_failure_cannot_trigger_repair(self):
        fake = FakeRepairModel()
        invalid = verify(False, reason="DOCKER_TIMEOUT")
        with patch("agentforge_django.v06_repair.docker_verification",
                   return_value=invalid) as docker:
            result = produce_candidate_v06(fake, self.root, REQUEST, ["app/**"])
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(fake.calls, 3)
        self.assertEqual(docker.call_count, 1)

    def test_exhausted_failed_repair_never_proposed(self):
        fake = FakeRepairModel()
        with patch("agentforge_django.v06_repair.docker_verification",
                   side_effect=[verify(False), verify(False)]) as docker:
            result = produce_candidate_v06(fake, self.root, REQUEST, ["app/**"])
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["budget"]["docker_verification_rounds"], 2)
        self.assertEqual(fake.calls, 5)
        self.assertIsNone(result["candidate_patch"])

    def test_model_receives_only_sanitized_docker_status(self):
        class Inspect(FakeRepairModel):
            def complete_model(self, system, user, schema):
                if "Fixer" in system:
                    assert "SENSITIVE_TOKEN" not in user
                    assert "stderr" not in user
                    assert "stdout" not in user
                return super().complete_model(system, user, schema)
        with patch("agentforge_django.v06_repair.docker_verification",
                   side_effect=[verify(False, reason="ASSERTION_FAILURE", secret=True),
                                verify(True)]):
            result = produce_candidate_v06(Inspect(), self.root, REQUEST, ["app/**"])
        self.assertEqual(result["status"], "PROPOSED")

    def test_unauthorized_scope_and_empty_request_denied(self):
        fake = FakeRepairModel()
        with self.assertRaises(BoundaryDenied):
            produce_candidate_v06(fake, self.root, REQUEST, ["**/*"])
        with self.assertRaises(BoundaryDenied):
            produce_candidate_v06(fake, self.root, "", ["app/**"])

    def test_max_role_request_and_docker_budgets_are_hard(self):
        fake = FakeRepairModel()
        budget = Budget(max_calls=1, max_validations=0)
        budget.call(fake, "Planner", json.dumps({"request": REQUEST}),
                    __import__("agentforge_django.v05_coding", fromlist=["CodingPlan"]).CodingPlan)
        with self.assertRaises(BoundaryDenied):
            budget.call(fake, "Planner", "anything",
                        __import__("agentforge_django.v05_coding", fromlist=["CodingPlan"]).CodingPlan)
        with self.assertRaises(BoundaryDenied):
            budget.verify(self.root)
