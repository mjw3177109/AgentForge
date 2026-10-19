#!/usr/bin/env python3
"""Three independent FAKE-agent repairs with REAL offline Docker checks each time.

CI result: SYNTHETIC_AGENT_REAL_DOCKER only; NEVER fake a real DeepSeek 3/3.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")
import django
django.setup()

from agentforge_django.v05_coding import produce_candidate
from agentforge_django.v05_fixture import REQUEST, ScriptedFakeAgent, make_fixture
from agentforge_django.verification import isolated_verification


def run_offline_three():
    rounds = []
    for number in range(1, 4):
        with tempfile.TemporaryDirectory(prefix="agentforge-v05-smoke-") as directory:
            fixture = make_fixture(Path(directory) / "source")
            baseline = isolated_verification(fixture, with_tests=True)
            if baseline["passed"] or not baseline["business_tests_executed"]:
                rounds.append({"round": number, "status": "FAIL", "reason": "BASELINE_INVALID"})
                continue
            broker = ScriptedFakeAgent()
            candidate = produce_candidate(broker, fixture, REQUEST, ["app/**"])
            original_unchanged = "return a - b" in (
                fixture / "app" / "views.py"
            ).read_text("utf-8")
            passed = (
                candidate["status"] == "PROPOSED"
                and candidate.get("independent_verification", {}).get("passed") is True
                and original_unchanged and broker.calls == 3
            )
            rounds.append({
                "round": number,
                "status": "PASS" if passed else "FAIL",
                "model": "SCRIPTED_FAKE_AGENT",
                "validator": "REAL_OFFLINE_DOCKER",
                "model_calls": broker.calls,
                "baseline_passed": baseline["passed"],
                "candidate_status": candidate["status"],
                "original_unchanged": original_unchanged,
            })
    return {
        "gate": "SYNTHETIC_AGENT_REAL_DOCKER",
        "rounds_required": 3,
        "rounds_passed": sum(x["status"] == "PASS" for x in rounds),
        "rounds": rounds,
        "real_deepseek_tested": False,
        "production_release_authorized": False,
    }


def main():
    result = run_offline_three()
    print(json.dumps(result))
    if result["rounds_passed"] != 3:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
