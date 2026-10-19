#!/usr/bin/env python3
"""V1.1 three-case offline benchmark with SCRIPTED agents and REAL Docker."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")

import django
django.setup()

from agentforge_django.v11_fake_agent import FakeScenarioAgent
from agentforge_django.v11_runner import run_three_case_suite


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/django-v11/offline-report.json")
    args = parser.parse_args()
    # Guard: this entrypoint never fetches model credentials or contacts LLM.
    result = run_three_case_suite(
        lambda case: FakeScenarioAgent(case),
        model_kind="SCRIPTED_FAKE_AGENT",
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "overall": result["overall"],
        "cases_passed": result["cases_passed"],
        "model_kind": result["model_kind"],
        "report": str(output),
    }, ensure_ascii=False))
    raise SystemExit(0 if result["overall"] == "PASS" else 2)


if __name__ == "__main__":
    main()
