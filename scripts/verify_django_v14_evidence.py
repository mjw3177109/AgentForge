#!/usr/bin/env python3
"""Verify case evidence, save digest receipt; no network/model/Docker calls."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_tests.settings")

from agentforge_django.v14_evidence import (
    EvidenceRejected, verify_benchmark, digest_report_bytes,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-model", choices=("SCRIPTED_FAKE_AGENT", "REAL_DEEPSEEK"),
                        required=True)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    source, destination = Path(args.input), Path(args.output)
    if source.resolve() == destination.resolve():
        parser.error("Verification receipt must be a distinct file")
    result = {
        "schema": "agentforge.django.v14.evidence-receipt.v1",
        "consistent": False,
        "pass_claim_supported_by_report": False,
        "expected_model_kind": args.expected_model,
        "independent_provider_identity_attested": False,
        "production_release_authorized": False,
    }
    try:
        if source.stat().st_size > 500000:
            raise EvidenceRejected("Benchmark evidence size exceeds limit")
        raw = source.read_bytes()
        report = json.loads(raw)
        verified = verify_benchmark(report, expected_model=args.expected_model)
        result.update(verified)
        result["report_sha256"] = digest_report_bytes(raw)
        if args.require_pass and not verified["pass_claim_supported_by_report"]:
            raise EvidenceRejected("The benchmark did not pass all three cases")
        ok = True
    except (ValueError, OSError, TypeError) as exc:
        ok = False
        # Never store untrusted message text (may include model response/secrets).
        result["failure_class"] = "REPORT_REJECTED_OR_INCOMPLETE"
        result["error_type"] = type(exc).__name__[:64]
        result["consistent"] = False
        result["pass_claim_supported_by_report"] = False
        result.pop("report_sha256", None)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".agentforge-v14-receipt-", dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print(json.dumps({
        "consistent": result["consistent"],
        "pass_claim_supported_by_report": result["pass_claim_supported_by_report"],
        "receipt": str(destination),
    }, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
