"""Run independent acceptance cases with actual offline Docker verification.

Callers supply the agent factory and must explicitly identify REAL vs FAKE.
The same test suite and grading apply to both modes.
"""
import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .docker_verify import docker_verification
from .live_evidence import failed_round
from .v06_repair import produce_candidate_v06
from .v11_benchmark import SCENARIOS, make_scenario, suite_fingerprint
from .v11_evaluation import grade_case, summarize_suite, test_count
from .v12_reporting import attach_case_telemetry, attach_suite_metrics
from .v13_provenance import assert_real_client


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_three_case_suite(model_factory, *, model_kind, on_case=None):
    if model_kind not in ("REAL_DEEPSEEK", "SCRIPTED_FAKE_AGENT"):
        raise ValueError("Unsupported model provenance")
    # Paid mode: test EVERY immutable baseline in real Docker BEFORE
    # constructing a provider client or making any paid model request.
    if model_kind == "REAL_DEEPSEEK":
        preflight = []
        for scenario in SCENARIOS:
            try:
                with tempfile.TemporaryDirectory(prefix="af-v13-preflight-") as td:
                    fixture = make_scenario(Path(td) / "source", scenario)
                    result = docker_verification(fixture, with_tests=True, timeout=90)
                    baseline_ok = (
                        result.get("backend") == "docker-offline"
                        and result.get("passed") is False
                        and result.get("business_tests_executed") is True
                        and test_count(result) >= scenario.minimum_tests
                    )
                    preflight.append(baseline_ok)
            except Exception:
                preflight.append(False)
        if not all(preflight):
            raise RuntimeError("REAL_MODEL_PREFLIGHT_FAILED_NO_PAID_CALLS")
    results = []
    for case in SCENARIOS:
        client = None
        verified_client = False
        try:
            with tempfile.TemporaryDirectory(prefix="agentforge-v11-") as tmp:
                root = make_scenario(Path(tmp) / "source", case)
                target = root / case.target_path
                tests = root / "app/tests.py"
                before = (_sha(target), _sha(tests))
                baseline = docker_verification(root, with_tests=True, timeout=90)
                baseline_count = test_count(baseline)
                baseline_valid = (
                    baseline.get("backend") == "docker-offline"
                    and baseline.get("passed") is False
                    and baseline.get("business_tests_executed") is True
                    and baseline_count >= case.minimum_tests
                )
                if not baseline_valid:
                    results.append({
                        "case_id": case.identifier,
                        "category": case.category,
                        "status": "FAIL",
                        "failure_class": "INVALID_FAILING_BASELINE_OR_DOCKER",
                        "baseline_test_count": baseline_count,
                        "source_untouched": (_sha(target), _sha(tests)) == before,
                    })
                    continue
                client = model_factory(case)
                if model_kind == "REAL_DEEPSEEK":
                    assert_real_client(client)
                    verified_client = True
                candidate = produce_candidate_v06(
                    client, root, case.requirement, ["app/**"],
                )
                original_unchanged = (_sha(target), _sha(tests)) == before
                count = candidate.get("independent_verification", {}).get(
                    "business_test_count", 0
                )
                result = grade_case(
                    case, candidate, calls=client.calls,
                    source_untouched=original_unchanged,
                    baseline_failed=True,
                    baseline_tests_executed=True,
                    final_tests_count=count,
                )
                result["baseline_test_count"] = baseline_count
                result["original_source_sha256"] = before[0]
                result["original_test_sha256"] = before[1]
                results.append(result)
        except Exception as exc:
            result = failed_round(case.identifier, exc)
            result["case_id"] = case.identifier
            result["category"] = case.category
            results.append(result)
        finally:
            if results and results[-1].get("case_id") == case.identifier:
                attach_case_telemetry(results[-1], client, model_kind)
                if model_kind == "REAL_DEEPSEEK":
                    results[-1]["v13_trusted_broker_checked"] = verified_client
                if on_case is not None:
                    on_case(list(results))
    summary = summarize_suite(
        results, manifest_sha256=suite_fingerprint(), model_kind=model_kind
    )
    if model_kind == "REAL_DEEPSEEK":
        if not all(r.get("v13_trusted_broker_checked") is True for r in results):
            summary["real_model_verified"] = False
            summary["overall"] = "FAIL"
            summary["failure_class"] = "UNTRUSTED_REAL_MODEL_PROVENANCE"
    summary["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    attach_suite_metrics(summary)
    summary["candidate_only"] = True
    summary["source_or_test_files_committed"] = False
    return summary
