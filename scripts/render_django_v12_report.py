#!/usr/bin/env python3
"""Render source-free benchmark markdown. Input provenance is self-reported only."""
import argparse
import json
from pathlib import Path

CASES = ("arith-001", "pricing-002", "access-003")
STATUSES = ("PASS", "FAIL", "BLOCKED")
COVERAGES = ("NOT_APPLICABLE", "COMPLETE", "PARTIAL", "UNKNOWN")


def number(value):
    return str(value) if type(value) is int and 0 <= value <= 10000000 else "unknown"


def choose(value, options):
    return value if value in options else "UNKNOWN"


def render(report):
    kind = report.get("model_kind")
    provenance = {
        "SCRIPTED_FAKE_AGENT": "Scripted agent (not real DeepSeek)",
        "REAL_DEEPSEEK": "Reported REAL_DEEPSEEK — verify signed CI and provider evidence",
    }.get(kind, "Unverified provenance")
    metrics = report.get("v12_metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    coverage = choose(metrics.get("provider_usage_coverage"), COVERAGES)
    lines = [
        "# AgentForge Django V1.2 验收报告", "",
        "- 模型来源：" + provenance,
        "- 总体结果：" + choose(report.get("overall"), STATUSES),
        "- 通过案例：" + number(report.get("cases_passed")) + "/3",
        "- 已记录角色请求：" + number(metrics.get("total_model_requests_observed")),
        "- Provider token 证据覆盖：" + coverage,
        "- 真实支付金额：未知（不能视为 0）", "",
        "| 案例 | 结果 | 修复路径 | 实测用例数 | 角色请求 | Token 覆盖 |",
        "|---|---|---|---:|---:|---|",
    ]
    cases = report.get("cases")
    if not isinstance(cases, list):
        cases = []
    items = {c.get("case_id"): c for c in cases
             if isinstance(c, dict) and c.get("case_id") in CASES}
    for case_id in CASES:
        item = items.get(case_id, {})
        evidence = item.get("model_evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        lines.append(
            "| " + case_id + " | " +
            choose(item.get("status"), STATUSES) + " | " +
            choose(item.get("repair_path"),
                   ("ONE_REPAIR", "NO_REPAIR", "NOT_RECORDED")) + " | " +
            number(item.get("final_test_count")) + " | " +
            number(evidence.get("attempted_requests")) + " | " +
            choose(evidence.get("usage_coverage"), COVERAGES) + " |"
        )
    lines.extend([
        "",
        "此报告仅含脱敏指标。模拟 Agent 通过不等于真实 DeepSeek 通过；"
        "真实模型合成测试通过不等于生产项目已就绪。", "",
    ])
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    source = Path(args.input)
    if source.stat().st_size > 500000:
        p.error("Benchmark report too large")
    payload = json.loads(source.read_text("utf-8"))
    if not isinstance(payload, dict):
        p.error("Expected JSON report object")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(payload), encoding="utf-8")
    print(str(output))


if __name__ == "__main__":
    main()
