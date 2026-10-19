#!/usr/bin/env python3
"""3 independent REAL DeepSeek bounded-coding cycles, fixed synthetic Django.

Run ONLY with --confirm-paid-calls and trusted Docker/DeepSeek credentials.
No real user/business source is used; no production approval or release occurs.
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
from agentforge_django.v05_fixture import REQUEST, make_fixture
from agentforge_django.v06_repair import produce_candidate_v06
from agentforge_django.live_evidence import summarize_candidate, failed_round


def run_live():
    runs = []
    for index in range(1, 4):
        try:
            with tempfile.TemporaryDirectory(prefix="af-v06-paid-") as temp:
                root = make_fixture(Path(temp) / "source")
                with override_settings(AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=True):
                    broker = create_v05_broker(max_requests=5)
                candidate = produce_candidate_v06(
                    broker, root, REQUEST, ["app/**"]
                )
                gate = candidate.get("independent_verification", {})
                untouched = "return a - b" in (
                    root / "app/views.py"
                ).read_text("utf-8")
                runs.append(summarize_candidate(
                    index, candidate, calls=broker.calls, source_untouched=untouched,
                ))
        except Exception as exc:
            runs.append(failed_round(index, exc))
    count = sum(item["status"] == "PASS" for item in runs)
    return {
        "schema": "agentforge.django.v06.real-coding.v1",
        "gate": "REAL_DEEPSEEK_SYNTHETIC_FIXTURE_ONLY",
        "rounds_required": 3, "rounds_passed": count,
        "overall": "PASS" if count == 3 else "FAIL",
        "rounds": runs,
        "production_release_authorized": False,
        "real_customer_project_verified": False,
        "hostile_code_isolation_proven": False,
        "actual_spend_measured": False,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid-calls", action="store_true")
    parser.add_argument("--output", default="artifacts/django-v06-live/summary.json")
    args = parser.parse_args()
    if not args.confirm_paid_calls:
        parser.error("Explicit consent required for potentially paid API calls")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not os.environ.get("AGENTFORGE_LLM_API_KEY"):
            raise ValueError("A real DeepSeek key is required")
        result = run_live()
    except Exception as exc:
        result = {
            "schema": "agentforge.django.v06.real-coding.v1",
            "overall": "BLOCKED",
            "rounds_required": 3, "rounds_passed": 0,
            "rounds": [], "error_type": type(exc).__name__,
            "production_release_authorized": False,
        }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "overall": result["overall"],
        "rounds_passed": result["rounds_passed"],
        "report": str(output),
    }, ensure_ascii=False))
    raise SystemExit(0 if result["overall"] == "PASS" else 2)


if __name__ == "__main__":
    main()
