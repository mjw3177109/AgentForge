"""Strict P4.1 V3-P2 canary accounting; never approves production release."""
from __future__ import annotations

from typing import Any
from agentforge.evidence_v3 import EXPECTED_V20_GATES

REQUIRED_AGENTS = frozenset({"database", "backend", "miniapp", "admin"})


def assess_canary_round(result: dict[str, Any], *, flag_was_injected: bool) -> dict[str, Any]:
    """A reported PASS is never enough: require actual opt-in invocation and 10 gates."""
    issues: list[str] = []
    if not flag_was_injected:
        issues.append("V3_P2_OPT_IN_MARKER_MISSING")
    if result.get("status") != "PASS" or result.get("stage") != "passed":
        issues.append("ROUND_NOT_PASSED")
    if result.get("review_status") != "APPROVE":
        issues.append("REVIEWER_NOT_APPROVE")
    initial = result.get("initial_agents")
    if not isinstance(initial, list) or len(initial) != 4 or set(initial) != REQUIRED_AGENTS:
        issues.append("FOUR_AGENT_EVIDENCE_MISSING")
    gates = result.get("gates")
    if not isinstance(gates, list):
        issues.append("GATES_NOT_LIST")
    else:
        names = [gate.get("name") for gate in gates if isinstance(gate, dict)]
        if len(gates) != len(EXPECTED_V20_GATES) or set(names) != set(EXPECTED_V20_GATES) or len(names) != len(gates):
            issues.append("INDEPENDENT_GATE_COVERAGE_MISMATCH")
        if any(not isinstance(g, dict) or g.get("status") != "PASS" or g.get("exit_code") != 0 for g in gates):
            issues.append("INDEPENDENT_GATE_FAILED")
    return {"status": "PASS" if not issues else "FAIL", "issues": issues,
            "production_release_authorized": False}


def assess_canary_summary(summary: dict[str, Any], rounds: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    if len(rounds) != 3 or [r.get("round") for r in rounds] != [1, 2, 3]:
        issues.append("THREE_FRESH_ROUNDS_REQUIRED")
    if summary.get("overall") != "PASS" or summary.get("rounds_required") != 3 or summary.get("rounds_passed") != 3:
        issues.append("V20_SUMMARY_NOT_3_OF_3_PASS")
    if summary.get("results") != rounds:
        issues.append("V20_SUMMARY_ROUND_MISMATCH")
    if summary.get("v3_canary_mode") != "V3_P2_SAFE_REPAIR_OPT_IN":
        issues.append("V3_P2_MODE_NOT_RECORDED")
    for item in rounds:
        result = assess_canary_round(item, flag_was_injected=item.get("v3_safe_repair_flag_injected") is True)
        if result["status"] != "PASS":
            issues.append(f"ROUND_{item.get('round')}_CANARY_FAILED:" + ",".join(result["issues"]))
    return {"status": "V3_P2_CANARY_3_OF_3_PASS" if not issues else "BLOCKED",
            "issues": issues, "authenticated": False,
            "requires_independent_p1_attestation": True,
            "production_release_authorized": False, "automated_merge_authorized": False}
