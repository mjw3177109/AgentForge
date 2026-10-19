"""V1.5 fail-closed coherence checks for role order, repair budgets and API usage.

These are INTERNAL report checks. The report remains self-reported;
they are not a cryptographic external DeepSeek attestation.
"""
from .v12_reporting import ROLES


def check_model_telemetry(case, expected_kind, reject):
    e = case["model_evidence"]
    calls = e.get("attempted_requests")
    trace = e.get("role_trace")
    repair = case.get("repair_attempts")
    pass_case = case["status"] == "PASS"
    reject(case.get("role_schema_accepted") == sum(
        x.get("status") == "SCHEMA_ACCEPTED" for x in trace
    ), "Role schema acceptance counter inconsistent")

    if calls is not None and trace:
        reject(len(trace) == calls, "Reported role requests do not match trace")

    if pass_case:
        reject(repair in (0, 1) and type(repair) is int,
               "Passing case must record repair count 0 or 1")
        expected = (
            ["Planner", "Executor", "Reviewer"] if repair == 0 else
            ["Planner", "Executor", "Reviewer", "Fixer", "Reviewer"]
        )
        reject([x["role"] for x in trace] == expected,
               "Invalid Planner/Executor/Reviewer/Fixer role sequence")
        reject(all(x["status"] == "SCHEMA_ACCEPTED" for x in trace),
               "Passing case contains failed or pending model role")
        reject(calls == len(expected),
               "Role count and repair count disagree")
        reject(case.get("repair_path") == (
            "NO_REPAIR" if repair == 0 else "ONE_REPAIR"
        ), "Repair-path metric inconsistent")
        reject(case.get("docker_verification_rounds") == repair + 1,
               "Independent Docker verification count inconsistent")

    if expected_kind != "REAL_DEEPSEEK":
        reject(e.get("spend_usd") is None, "Synthetic case cannot claim paid spend")
        return
    reports = e.get("provider_usage_reports")
    coverage = e.get("usage_coverage")
    tokens = e.get("observed_tokens")
    reject(type(reports) is int and 0 <= reports <= 5 and
           (calls is None or reports <= calls),
           "Provider usage report count exceeds API calls")
    if coverage == "UNKNOWN":
        reject(reports == 0 and tokens is None,
               "Unknown usage must have no claimed token count")
    else:
        reject(coverage in ("COMPLETE", "PARTIAL"),
               "Invalid provider usage state")
        reject(reports > 0, "Token usage requires provider responses")
        reject(isinstance(tokens, dict) and all(
            type(tokens.get(key)) is int and 0 <= tokens[key] <= 10000000
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        ), "Provider usage tokens are invalid")
        reject(tokens["total_tokens"] >= tokens["prompt_tokens"] and
               tokens["total_tokens"] >= tokens["completion_tokens"],
               "Provider token breakdown inconsistent")
        if coverage == "COMPLETE":
            reject(calls is not None and calls > 0 and reports == calls,
                   "Complete token coverage must match all requests")
        else:
            reject(calls is None or 0 < reports < calls,
                   "Partial token coverage cannot claim all requests")
    reject(e.get("spend_usd") is None,
           "Currency spend is not independently verified")


def check_suite_telemetry(report, expected_kind, reject):
    cases = report["cases"]
    m = report["v12_metrics"]
    evidences = [case["model_evidence"] for case in cases]
    reject(m.get("requests_with_missing_count") ==
           sum(e.get("attempted_requests") is None for e in evidences),
           "Missing request-count metric disagrees with cases")
    reject(m.get("cases_passing_after_one_repair") == sum(
        c["status"] == "PASS" and c.get("repair_path") == "ONE_REPAIR"
        for c in cases
    ), "Repair-success metric disagrees with cases")
    role_totals = m.get("role_schema_acceptances")
    reject(isinstance(role_totals, dict) and all(
        role_totals.get(role) == sum(
            event.get("role") == role and event.get("status") == "SCHEMA_ACCEPTED"
            for e in evidences for event in e["role_trace"]
        ) for role in ROLES
    ), "Role totals disagree with case traces")
    if expected_kind == "SCRIPTED_FAKE_AGENT":
        reject(m.get("provider_token_reports_received") is None,
               "Fake benchmark must not claim provider usage reports")
        return
    reports = sum(e["provider_usage_reports"] for e in evidences)
    reject(m.get("provider_token_reports_received") == reports,
           "Provider usage report total disagrees with cases")
    counted = [e for e in evidences if e["observed_tokens"] is not None]
    if not counted:
        expected_coverage, expected_tokens = "UNKNOWN", None
    else:
        expected_coverage = (
            "COMPLETE" if len(counted) == 3 and all(
                e["usage_coverage"] == "COMPLETE" for e in evidences
            ) else "PARTIAL"
        )
        expected_tokens = {key: sum(
            e["observed_tokens"][key] for e in counted
        ) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    reject(m.get("provider_usage_coverage") == expected_coverage and
           m.get("observed_tokens") == expected_tokens,
           "Aggregate provider tokens or coverage inconsistent")
