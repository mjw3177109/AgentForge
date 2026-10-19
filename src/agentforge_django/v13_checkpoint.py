"""Atomic redacted checkpoint output during paid multi-case acceptance.

Checkpoints intentionally never mark a partial suite PASS and never claim
that real API calls occurred. Workflow logs/provider billing are required.
"""
import json
import os
import tempfile
from pathlib import Path


def write_checkpoint(path, *, cases, manifest, model_kind):
    target = Path(path)
    if not target.parent.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
    safe_cases = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        safe_cases.append({
            "case_id": case.get("case_id") if case.get("case_id") in
                ("arith-001", "pricing-002", "access-003") else "UNKNOWN",
            "status": case.get("status") if case.get("status") in
                ("PASS", "FAIL", "BLOCKED") else "FAIL",
            "failure_class": (
                case.get("failure_class") if case.get("failure_class") in (
                    "MODEL_REVIEW_REJECTED",
                    "POLICY_BLOCKED",
                    "INDEPENDENT_BEHAVIORAL_TEST_FAILED",
                    "VERIFICATION_INFRASTRUCTURE",
                    "INVALID_FAILING_BASELINE_OR_DOCKER",
                    "POLICY_OR_PRECONDITION",
                    "MODEL_TRANSPORT_OR_SCHEMA",
                    "EXECUTION_TIMEOUT",
                    "EXECUTION_ENVIRONMENT",
                    "UNEXPECTED_PIPELINE_EXCEPTION",
                    "MISSING_ACCEPTANCE_EVIDENCE",
                ) else "OTHER_OR_UNCLASSIFIED"
            ),
            "requests_observed": (
                case.get("model_evidence", {}).get("attempted_requests")
                if isinstance(case.get("model_evidence"), dict)
                and type(case["model_evidence"].get("attempted_requests")) is int
                else None
            ),
        })
    record = {
        "schema": "agentforge.django.v13.checkpoint.v1",
        "phase": "INCOMPLETE_UNTIL_FINAL_REPORT",
        "model_kind_label": model_kind if model_kind in
            ("REAL_DEEPSEEK", "SCRIPTED_FAKE_AGENT") else "UNKNOWN",
        "suite_fingerprint": manifest,
        "cases_finished": len(safe_cases),
        "cases": safe_cases,
        "real_model_verified": False,
        "production_release_authorized": False,
    }
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2).encode()
    fd, tmp = tempfile.mkstemp(prefix=".agentforge-v13-", dir=str(target.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return record
