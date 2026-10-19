"""V1.1 benchmark manifests, independent fixtures, and fail-closed scoring."""
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from agentforge_django.v11_benchmark import SCENARIOS, make_scenario, suite_fingerprint
from agentforge_django.v11_evaluation import (
    grade_case, summarize_suite, test_count, ran_at_least_tests,
)
from agentforge_django.v11_fake_agent import FakeScenarioAgent


class BenchmarkFixturesTests(SimpleTestCase):
    def test_three_distinct_synthetic_cases(self):
        self.assertEqual(
            [case.identifier for case in SCENARIOS],
            ["arith-001", "pricing-002", "access-003"],
        )
        self.assertEqual(len({case.target_path for case in SCENARIOS}), 3)
        self.assertEqual(len({case.source for case in SCENARIOS}), 3)
        self.assertEqual(len(suite_fingerprint()), 64)

    def test_original_case_source_and_tests_match_manifest(self):
        for case in SCENARIOS:
            with self.subTest(case=case.identifier):
                with tempfile.TemporaryDirectory() as tmp:
                    root = make_scenario(Path(tmp) / "project", case)
                    source = (root / case.target_path).read_text("utf-8")
                    tests = (root / "app/tests.py").read_text("utf-8")
                    self.assertEqual(
                        hashlib.sha256(source.encode()).hexdigest(),
                        case.manifest()["source_sha256"],
                    )
                    self.assertEqual(
                        hashlib.sha256(tests.encode()).hexdigest(),
                        case.manifest()["tests_sha256"],
                    )
                    self.assertGreaterEqual(tests.count("def test_"), case.minimum_tests)

    def test_fake_agent_cannot_be_misrepresented_as_real(self):
        # Even if every fake case passes, provenance remains explicit.
        report = summarize_suite([
            {"case_id": c.identifier, "status": "PASS"} for c in SCENARIOS
        ], manifest_sha256=suite_fingerprint(), model_kind="SCRIPTED_FAKE_AGENT")
        self.assertEqual(report["overall"], "PASS")
        self.assertFalse(report["real_model_verified"])
        self.assertFalse(report["production_release_authorized"])

    def test_invalid_final_business_count_blocks_candidate(self):
        case = SCENARIOS[2]
        candidate = {
            "status": "PROPOSED", "patch_sha256": "a" * 64,
            "production_release_authorized": False,
            "independent_verification": {
                "backend": "docker-offline", "passed": True,
                "business_tests_executed": True,
                "checks": [{"success": True}, {"success": True}],
            },
        }
        out = grade_case(
            case, candidate, calls=3, source_untouched=True,
            baseline_failed=True, baseline_tests_executed=True,
            final_tests_count=1,
        )
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["failure_class"], "BENCHMARK_INCOMPLETE_OR_TEST_COVERAGE")

    def test_no_failed_baseline_cannot_count(self):
        case = SCENARIOS[0]
        candidate = {
            "status": "PROPOSED", "patch_sha256": "a" * 64,
            "production_release_authorized": False,
            "independent_verification": {
                "backend": "docker-offline", "passed": True,
                "business_tests_executed": True,
                "checks": [{"success": True}, {"success": True}],
            },
        }
        out = grade_case(
            case, candidate, calls=3, source_untouched=True,
            baseline_failed=False, baseline_tests_executed=True,
            final_tests_count=100,
        )
        self.assertEqual(out["status"], "FAIL")

    def test_suite_requires_all_three_ids_in_order(self):
        report = summarize_suite(
            [{"case_id": SCENARIOS[0].identifier, "status": "PASS"}] * 3,
            manifest_sha256=suite_fingerprint(), model_kind="REAL_DEEPSEEK",
        )
        self.assertEqual(report["overall"], "FAIL")
        self.assertFalse(report["real_model_verified"])

    def test_test_count_extraction_and_no_zero_shortcut(self):
        raw = {"checks": [
            {"stdout": "system check", "success": True},
            {"stderr": "Ran 5 tests in 0.42s", "success": True},
        ]}
        self.assertEqual(test_count(raw), 5)
        self.assertTrue(ran_at_least_tests(raw["checks"], 5))
        self.assertFalse(ran_at_least_tests(raw["checks"], 6))
        self.assertEqual(test_count({"checks": []}), 0)
