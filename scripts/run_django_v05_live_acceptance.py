#!/usr/bin/env python3
"""9 real DeepSeek role calls across 3 independent candidate+Docker rounds.

Requires opt-in paid API usage and available Docker verifier. A successful run
proves only this fixed tiny Django fixture, NOT production autonomous stability.
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")
import django
django.setup()

from django.test.utils import override_settings
from agentforge_django.v05_broker import create_v05_broker
from agentforge_django.v05_coding import produce_candidate
from agentforge_django.v05_fixture import REQUEST, make_fixture


def run_live_three():
    reports = []
    for index in range(1, 4):
        calls = 0
        try:
            with tempfile.TemporaryDirectory(prefix="agentforge-v05-live-") as tmp:
                root = make_fixture(Path(tmp) / "fixture")
                with override_settings(AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=True):
                    broker = create_v05_broker()
                outcome = produce_candidate(broker, root, REQUEST, ["app/**"])
                calls = broker.calls
                original_preserved = "return a - b" in (
                    root / "app/views.py"
                ).read_text("utf-8")
                valid = (
                    outcome["status"] == "PROPOSED"
                    and outcome["review_decision"] == "APPROVE"
                    and outcome["independent_verification"]["passed"] is True
                    and outcome["independent_verification"]["business_tests_executed"] is True
                    and original_preserved
                    and calls == 3
                )
                reports.append({
                    "round": index,
                    "status": "PASS" if valid else "FAIL",
                    "reason": "VALIDATED_CANDIDATE" if valid else "GATE_MISMATCH",
                    "model_calls": calls,
                    "review": outcome.get("review_decision"),
                    "patch_sha256": outcome.get("patch_sha256"),
                    "independent_docker": outcome.get("independent_verification", {}).get("passed", False),
                    "source_unchanged": original_preserved,
                })
        except Exception as exc:
            reports.append({
                "round": index, "status": "FAIL",
                "reason": "LLM_DOCKER_OR_POLICY_ERROR",
                "error_type": type(exc).__name__,
                "model_calls_observed": calls,
            })
    passed = sum(x["status"] == "PASS" for x in reports)
    return {
        "schema": "agentforge.django.v05.real-coding.v1",
        "fixture": "SYNTHETIC_DJANGO_ARITHMETIC",
        "rounds_required": 3,
        "rounds_passed": passed,
        "overall": "PASS" if passed == 3 else "FAIL",
        "rounds": reports,
        "verified_on_real_customer_project": False,
        "hostile_code_isolation_proven": False,
        "production_release_authorized": False,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid-calls", action="store_true")
    parser.add_argument("--output", default="artifacts/django-v05-live/summary.json")
    args = parser.parse_args()
    if not args.confirm_paid_calls:
        parser.error("Explicit --confirm-paid-calls required; may charge 9 DeepSeek requests")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not os.getenv("AGENTFORGE_LLM_API_KEY"):
            raise ValueError("Real LLM credentials missing")
        result = run_live_three()
    except Exception as exc:
        result = {
            "schema": "agentforge.django.v05.real-coding.v1",
            "overall": "BLOCKED", "rounds_required": 3, "rounds_passed": 0,
            "rounds": [], "error_type": type(exc).__name__,
            "production_release_authorized": False,
        }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"overall": result["overall"],
                      "rounds_passed": result["rounds_passed"],
                      "report": str(output)}, ensure_ascii=False))
    raise SystemExit(0 if result["overall"] == "PASS" else 2)


if __name__ == "__main__":
    main()
