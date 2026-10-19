#!/usr/bin/env python3
"""Paid, explicit V1.1 real DeepSeek 3-case benchmark. Never auto-deploys.

Maximum of five role requests per case: 15 logical API calls in total.
No customer source, customer data or arbitrary command execution by the model.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")
import django
django.setup()

from django.test.utils import override_settings
from agentforge_django.v05_broker import create_v05_broker
from agentforge_django.v11_runner import run_three_case_suite
from agentforge_django.v11_benchmark import suite_fingerprint
from agentforge_django.v13_checkpoint import write_checkpoint


def make_live_client(case):
    # Explicitly bound real provider/URL/model/limited request count.
    with override_settings(AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER=True):
        return create_v05_broker(max_requests=5)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--confirm-paid-calls", action="store_true")
    p.add_argument("--output", default="artifacts/django-v11-live/report.json")
    p.add_argument("--checkpoint", default=None)
    args = p.parse_args()
    if not args.confirm_paid_calls:
        p.error("Explicit --confirm-paid-calls is required for actual DeepSeek fees")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path = Path(args.checkpoint) if args.checkpoint else (
        output.parent / "checkpoint.json"
    )
    if checkpoint_path.resolve() == output.resolve():
        p.error("Checkpoint and final report paths must differ")
    if not os.environ.get("AGENTFORGE_LLM_API_KEY"):
        result = {
            "schema": "agentforge.django.v11.benchmark.v1",
            "overall": "BLOCKED",
            "failure_class": "REAL_DEEPSEEK_CREDENTIAL_NOT_AVAILABLE",
            "cases_passed": 0, "case_count": 3, "cases": [],
            "real_model_verified": False,
            "production_release_authorized": False,
        }
    else:
        try:
            result = run_three_case_suite(
                make_live_client,
                model_kind="REAL_DEEPSEEK",
                on_case=lambda cases: write_checkpoint(
                    checkpoint_path, cases=cases, manifest=suite_fingerprint(),
                    model_kind="REAL_DEEPSEEK",
                ),
            )
        except Exception as exc:
            # A failing paid preflight or checkpoint write may stop the suite.
            # This report NEVER publishes a partial run as successful.
            result = {
                "schema": "agentforge.django.v13.benchmark.v1",
                "overall": "BLOCKED", "failure_class": "PREFLIGHT_OR_REPORT_ERROR",
                "error_type": type(exc).__name__[:64],
                "cases_passed": 0, "case_count": 3, "cases": [],
                "real_model_verified": False,
                "production_release_authorized": False,
            }
    result["real_model_claim_requires_provider_confirmation"] = True
    output.write_text(json.dumps(
        result, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n", "utf-8")
    print(json.dumps({
        "overall": result["overall"],
        "cases_passed": result["cases_passed"],
        "case_count": 3,
        "report": str(output),
    }, ensure_ascii=False))
    raise SystemExit(0 if result["overall"] == "PASS" else 2)


if __name__ == "__main__":
    main()
