"""V1.2 trustworthy provider-usage and per-role acceptance reporting.

Never invent tokens, infer USD spend, or let fake clients claim real usage.
All output is finite, structurally bounded and stripped of source/prompts.
"""

ROLES = ("Planner", "Executor", "Reviewer", "Fixer")


def _bounded_nonnegative(value):
    return type(value) is int and 0 <= value <= 10000000


def model_evidence(client, model_kind):
    if client is None:
        calls, trace = None, []
    else:
        raw_calls = getattr(client, "calls", None)
        calls = raw_calls if _bounded_nonnegative(raw_calls) and raw_calls <= 5 else None
        raw_trace = getattr(client, "v12_role_trace", None)
        trace = []
        if isinstance(raw_trace, list):
            for entry in raw_trace[:5]:
                if not isinstance(entry, dict):
                    continue
                role = entry.get("role")
                if role not in ROLES:
                    continue
                status = entry.get("status")
                if status not in ("ATTEMPTED", "SCHEMA_ACCEPTED", "ERROR"):
                    status = "ERROR"
                # Never retain exception type from an arbitrary plugin;
                # only known safe role/state fields are kept here.
                trace.append({"role": role, "status": status})
    result = {"attempted_requests": calls, "role_trace": trace}
    if model_kind != "REAL_DEEPSEEK":
        result.update({
            "provenance": "SCRIPTED_FAKE_AGENT", "provider_usage_reports": None,
            "usage_coverage": "NOT_APPLICABLE", "observed_tokens": None,
            "spend_usd": None,
        })
        return result

    reports = getattr(client, "usage_reports", None) if client is not None else None
    usage = getattr(client, "usage", None) if client is not None else None
    valid = (
        _bounded_nonnegative(reports)
        and isinstance(usage, dict)
        and all(_bounded_nonnegative(usage.get(key))
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
        and usage["total_tokens"] >= usage["prompt_tokens"]
        and usage["total_tokens"] >= usage["completion_tokens"]
        and (calls is None or reports <= calls)
    )
    if valid and reports > 0:
        observed = {key: usage[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        coverage = "COMPLETE" if calls is not None and calls > 0 and reports == calls else "PARTIAL"
    else:
        observed = None
        reports = 0 if not valid else reports
        coverage = "UNKNOWN"
    result.update({
        "provenance": "REAL_DEEPSEEK",
        "provider_usage_reports": reports,
        "usage_coverage": coverage,
        "observed_tokens": observed,
        "spend_usd": None,
    })
    return result


def attach_case_telemetry(case, client, model_kind):
    info = model_evidence(client, model_kind)
    case["model_evidence"] = info
    case["role_schema_accepted"] = sum(
        x["status"] == "SCHEMA_ACCEPTED" for x in info["role_trace"]
    )
    repair = case.get("repair_attempts")
    case["repair_path"] = (
        "ONE_REPAIR" if repair == 1
        else "NO_REPAIR" if repair == 0
        else "NOT_RECORDED"
    )
    # Explicitly distinguish the actual Docker validator from model opinion.
    case["verification_kind"] = "OFFLINE_DOCKER" if (
        case.get("independent_test_passed") is True
    ) else "NOT_VERIFIED_AS_PASS"
    return case


def attach_suite_metrics(report):
    cases = report.get("cases", [])
    total = sum(
        case.get("model_evidence", {}).get("attempted_requests") or 0
        for case in cases if isinstance(case, dict)
    )
    real = report.get("model_kind") == "REAL_DEEPSEEK"
    counted = [
        case["model_evidence"] for case in cases
        if isinstance(case, dict)
        and isinstance(case.get("model_evidence"), dict)
    ]
    covered = [x for x in counted if x.get("observed_tokens") is not None]
    observed = None
    if covered:
        observed = {
            key: sum(x["observed_tokens"][key] for x in covered)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
    if not real:
        coverage = "NOT_APPLICABLE"
    elif counted and len(counted) == len(cases) and all(
        x["usage_coverage"] == "COMPLETE" for x in counted
    ):
        coverage = "COMPLETE"
    elif covered:
        coverage = "PARTIAL"
    else:
        coverage = "UNKNOWN"
    report["v12_metrics"] = {
        "total_model_requests_observed": total,
        "requests_with_missing_count": sum(
            x.get("attempted_requests") is None for x in counted
        ),
        "case_pass_rate": {
            "passed": report.get("cases_passed", 0),
            "total": report.get("case_count", len(cases)),
        },
        "cases_passing_after_one_repair": sum(
            x.get("status") == "PASS" and x.get("repair_path") == "ONE_REPAIR"
            for x in cases if isinstance(x, dict)
        ),
        "role_schema_acceptances": {
            role: sum(
                x.get("role") == role and x.get("status") == "SCHEMA_ACCEPTED"
                for info in counted for x in info["role_trace"]
            ) for role in ROLES
        },
        "provider_usage_coverage": coverage,
        "provider_token_reports_received": (
            sum(x.get("provider_usage_reports") or 0 for x in counted)
            if real else None
        ),
        "observed_tokens": observed if real else None,
        "observed_usd_spend": None,
        "model_cost_is_verified": False,
    }
    return report
