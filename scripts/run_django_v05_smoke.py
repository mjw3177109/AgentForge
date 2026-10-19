#!/usr/bin/env python3
"""One real Docker coding/validation smoke; LLM is SYNTHETIC, NOT DeepSeek."""
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


def main():
    with tempfile.TemporaryDirectory(prefix="agentforge-v05-smoke-") as directory:
        fixture = make_fixture(Path(directory) / "source")
        baseline = isolated_verification(fixture, with_tests=True)
        if baseline["passed"]:
            print("BASELINE_INVALID: pre-fix business tests unexpectedly passed")
            raise SystemExit(3)
        broker = ScriptedFakeAgent()
        outcome = produce_candidate(broker, fixture, REQUEST, ["app/**"])
        safe = {
            "stage": "SYNTHETIC_AGENT_REAL_DOCKER",
            "baseline_passed": baseline["passed"],
            "result": outcome["status"],
            "docker_validation_passed": outcome.get(
                "independent_verification", {}
            ).get("passed", False),
            "agent_calls": broker.calls,
            "original_unchanged": "return a - b" in
                (fixture / "app" / "views.py").read_text("utf-8"),
            "production_release_authorized": False,
        }
        print(json.dumps(safe))
        if not (
            outcome["status"] == "PROPOSED"
            and safe["docker_validation_passed"]
            and safe["original_unchanged"]
            and broker.calls == 3
        ):
            raise SystemExit(2)


if __name__ == "__main__":
    main()
