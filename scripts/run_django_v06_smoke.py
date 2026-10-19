#!/usr/bin/env python3
"""3x simulated Planner/Executor/Fixer/Reviewer, with REAL Docker tests."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")
import django
django.setup()

from agentforge_django.v05_fixture import REQUEST, make_fixture
from agentforge_django.v06_fixture import FakeRepairModel
from agentforge_django.v06_repair import produce_candidate_v06
from agentforge_django.docker_verify import docker_verification


def main():
    results = []
    for num in range(1, 4):
        with tempfile.TemporaryDirectory(prefix="af-v06-smoke-") as temp:
            original = make_fixture(Path(temp) / "source")
            baseline = docker_verification(original)
            if baseline["passed"]:
                raise SystemExit("Baseline must fail")
            fake = FakeRepairModel()
            candidate = produce_candidate_v06(fake, original, REQUEST, ["app/**"])
            untouched = "return a - b" in (original / "app/views.py").read_text("utf-8")
            passed = (
                candidate["status"] == "PROPOSED"
                and candidate["repair_attempts"] == 1
                and candidate["budget"]["role_requests"] == 5
                and candidate["budget"]["docker_verification_rounds"] == 2
                and candidate["independent_verification"]["passed"] is True
                and untouched
            )
            results.append({
                "round": num, "status": "PASS" if passed else "FAIL",
                "baseline_passed": False,
                "first_candidate_passed": candidate["rounds"][0]["verification"]["passed"],
                "final_docker_passed": candidate["independent_verification"]["passed"],
                "model": "SCRIPTED_FAKE_MODEL", "source_unchanged": untouched,
                "model_calls": fake.calls, "repair_attempts": candidate["repair_attempts"],
                "docker_verifications": candidate["budget"]["docker_verification_rounds"],
            })
    outcome = {
        "gate": "SYNTHETIC_AGENT_REAL_DOCKER_V06",
        "rounds_required": 3,
        "rounds_passed": sum(x["status"] == "PASS" for x in results),
        "rounds": results,
        "real_deepseek_tested": False,
        "production_release_authorized": False,
    }
    print(json.dumps(outcome))
    if outcome["rounds_passed"] != 3:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
