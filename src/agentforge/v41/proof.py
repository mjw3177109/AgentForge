"""Verify *executed* P2 runtime calls against autonomous protocol task records.

This module is strictly an accounting check, not proof that business logic is
correct.  Only an isolated runner with protected source and artifacts may issue
these records; V4.1 binds them to separate independently signed evidence.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
from typing import Any

AGENTS = frozenset({"database", "backend", "miniapp", "admin"})
SCHEMA = "agentforge.v41.p2-runtime-proof/1"


def evaluate_runtime_trace(trace: Any, protocol: Any) -> dict[str, Any]:
    issues: list[str] = []
    if not isinstance(trace, dict) or trace.get("schema") != SCHEMA:
        return {"status": "BLOCKED", "issues": ["TRACE_SCHEMA_INVALID"]}
    events = trace.get("invocations")
    task_runs = protocol.get("task_runs") if isinstance(protocol, dict) else None
    if not isinstance(events, list) or not events or len(events) > 128:
        return {"status": "BLOCKED", "issues": ["TRACE_EVENTS_INVALID"]}
    if not isinstance(task_runs, list) or not task_runs or len(task_runs) > 128:
        return {"status": "BLOCKED", "issues": ["PROTOCOL_TASK_RECORDS_INVALID"]}
    observed: Counter = Counter()
    expected: Counter = Counter()
    agents: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            issues.append("INVALID_EXECUTION_EVENT")
            continue
        task, agent, status = (event.get(x) for x in ("task_id", "agent", "status"))
        if (not isinstance(task, str) or not task.startswith("TASK-") or
                agent not in AGENTS or status not in {"SUCCESS", "BLOCKED", "FAILED"} or
                event.get("runtime") != "SafeRepairRuntime" or
                type(event.get("attempts")) is not int or event["attempts"] < 1):
            issues.append("UNTRUSTED_P2_INVOCATION")
            continue
        verified = event.get("verification")
        if not isinstance(verified, list) or not verified:
            issues.append("INDEPENDENT_VERIFICATION_NOT_EXECUTED")
        else:
            for check in verified:
                if (not isinstance(check, dict) or type(check.get("returncode")) is not int
                        or not isinstance(check.get("argv"), list)
                        or not check["argv"] or type(check.get("success")) is not bool
                        or check["success"] != (check["returncode"] == 0)):
                    issues.append("VERIFICATION_RESULT_MALFORMED")
                elif status == "SUCCESS" and not check["success"]:
                    issues.append("SUCCESS_WITH_FAILED_VERIFICATION")
        observed[(task, agent, status)] += 1
        agents.add(agent)
    for record in task_runs:
        if (not isinstance(record, dict) or not isinstance(record.get("task_id"), str)
                or record.get("agent") not in AGENTS
                or record.get("status") not in {"SUCCESS", "BLOCKED", "FAILED"}):
            issues.append("PROTOCOL_TASK_INVALID")
        else:
            expected[(record["task_id"], record["agent"], record["status"])] += 1
    if observed != expected:
        issues.append("P2_EXECUTIONS_DO_NOT_MATCH_TASK_RECORDS")
    if agents != AGENTS:
        issues.append("FOUR_AGENTS_DID_NOT_EXECUTE_P2")
    if len(events) != len(task_runs):
        issues.append("P2_INSTRUMENTATION_INCOMPLETE")
    return {"status": "PASS" if not issues else "BLOCKED",
            "issues": sorted(set(issues)), "executions": len(events),
            "agents": sorted(agents), "production_release_authorized": False}


def verify_trace_file(path: Path, protocol: dict[str, Any]) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 256_000:
            raise ValueError("Missing/symlink/oversized trace")
        return evaluate_runtime_trace(json.loads(path.read_text("utf-8")), protocol)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return {"status": "BLOCKED", "issues": ["TRACE_UNREADABLE"],
                "production_release_authorized": False}
