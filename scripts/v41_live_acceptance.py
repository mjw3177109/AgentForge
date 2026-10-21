#!/usr/bin/env python3
"""V4.1 paid manual-only canary: actual P2 execution + Java exactly-once.

Each round independently executes 4 Agents, Reviewer, the original V2 ten
post-run gates, and a *new* trusted Java/Spring/MySQL service behavior gate.
This is synthetic fixture evidence ONLY, not proof of production release.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from agentforge.v41.proof import verify_trace_file
from agentforge.v41.service_gate import check_java_service
from agentforge.acceptance_p41 import assess_canary_summary


def load_v20(repo: Path):
    source = repo / "scripts/run_v20_stability.py"
    if source.is_symlink() or not source.is_file():
        raise ValueError("REVIEWED_V20_RUNNER_MISSING")
    spec = importlib.util.spec_from_file_location("v41_trusted_v20", source)
    if spec is None or spec.loader is None:
        raise ValueError("REVIEWED_V20_RUNNER_INVALID")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_round(index: int, root: Path, seconds: int, *, repo: Path, v20, run_id: str) -> dict:
    folder = root / f"round_{index:02d}"
    if folder.exists() or folder.is_symlink():
        raise ValueError("ROUND_EVIDENCE_ALREADY_EXISTS")
    env = os.environ.copy()
    env["AGENTFORGE_BENCHMARK_ARTIFACT_DIR"] = str(folder)
    started = time.monotonic()
    try:
        cp = subprocess.run([sys.executable, "scripts/v41_hardened_benchmark.py"],
                            cwd=repo, env=env, shell=False, capture_output=True,
                            text=True, timeout=seconds)
        stdout, stderr, code = cp.stdout, cp.stderr, cp.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        code = 124
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "v20_runner_stdout.txt").write_text(stdout, "utf-8")
    (folder / "v20_runner_stderr.txt").write_text(stderr, "utf-8")
    try:
        protocol = json.loads(stdout)
    except (ValueError, TypeError):
        protocol = None
    stage, reason = v20.assess_result(protocol, code)
    p2 = verify_trace_file(folder / "p2_runtime_proof.json", protocol or {})
    if p2["status"] != "PASS":
        stage, reason = "p2_runtime_evidence", ",".join(p2["issues"])
    gates = []
    service = {"name": "java_mysql_service_exactly_once", "status": "NOT_RUN", "exit_code": 2,
               "reason": "Previous gate failed", "trusted_test_executed": False}
    if stage == "passed":
        snapshot = folder / "generated-repo"
        if not snapshot.is_dir() or snapshot.is_symlink():
            stage, reason = "snapshot_missing", "Generated repository evidence missing"
        else:
            gates = v20.verify_snapshot(snapshot, folder, index)
            failed = next((g for g in gates if g.get("status") != "PASS"), None)
            if failed:
                stage, reason = failed["name"], failed.get("error_excerpt") or "Immutable gate failed"
            elif len(gates) != 10:
                stage, reason = "immutable_gate_coverage", "Expected exactly ten V2 independent gates"
            else:
                service = check_java_service(
                    snapshot, folder, round_index=index, run_id=run_id,
                    trusted_java=repo / "benchmarks/v41_trusted/TrustedPointsExactlyOnceTest.java"
                )
                if service["status"] != "PASS":
                    stage, reason = "java_mysql_service_exactly_once", service["reason"]
    record = {
        "round": index, "status": "PASS" if stage == "passed" else "FAIL",
        "stage": stage, "reason": reason,
        "failure_class": None if stage == "passed" else (
            "P2_EXECUTION_NOT_PROVEN" if stage == "p2_runtime_evidence" else
            "JAVA_SERVICE_IDEMPOTENCY" if stage == "java_mysql_service_exactly_once" else
            v20.classify_failure(stage, reason + "\n" + stderr[-1000:])),
        "benchmark_exit_code": code,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "initial_agents": [x.get("agent") for x in (protocol or {}).get("task_runs", [])
                           if "review repair round" not in str(x.get("message", ""))],
        "repair_agents": [x.get("agent") for x in (protocol or {}).get("task_runs", [])
                          if "review repair round" in str(x.get("message", ""))],
        "review_status": ((protocol or {}).get("review") or {}).get("status"),
        "gates": gates, "v3_safe_repair_flag_injected": p2["status"] == "PASS",
        "v41_p2_executed": p2,
        "v41_service_gate": service,
    }
    (folder / "v20_result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=Path("artifacts/v41-live"))
    p.add_argument("--rounds", type=int, choices=[3], default=3)
    p.add_argument("--round-timeout", type=int, default=1200)
    args = p.parse_args(argv)
    if not 120 <= args.round_timeout <= 1200:
        p.error("ROUND_TIMEOUT_OUT_OF_RANGE")
    for name in ("GITHUB_ACTIONS", "GITHUB_RUN_ID", "AGENTFORGE_LLM_API_KEY",
                 "AGENTFORGE_LLM_BASE_URL", "AGENTFORGE_LLM_MODEL", "AGENTFORGE_V20_MYSQL_PASSWORD"):
        if not os.environ.get(name) or (name == "GITHUB_ACTIONS" and os.environ[name] != "true"):
            p.error("ISOLATED_REAL_MODEL_CONFIGURATION_REQUIRED:" + name)
    if not str(os.environ["GITHUB_RUN_ID"]).isdigit():
        p.error("INVALID_RUN_ID")
    repo = Path(__file__).resolve().parents[1]
    root = args.output_dir.absolute()
    if root.is_symlink() or root.exists() and any(root.iterdir()):
        p.error("REQUIRE_FRESH_EMPTY_ARTIFACT_ROOT")
    root.mkdir(parents=True, exist_ok=True)
    v20 = load_v20(repo)
    records = []
    for i in range(1, 4):
        record = run_round(i, root, args.round_timeout, repo=repo,
                           v20=v20, run_id=os.environ["GITHUB_RUN_ID"])
        records.append(record)
        print(json.dumps({k: record[k] for k in ("round", "status", "stage", "review_status")}), flush=True)
    passed = sum(r["status"] == "PASS" for r in records)
    summary = {"overall": "PASS" if passed == 3 else "FAIL",
               "rounds_required": 3, "rounds_passed": passed,
               "all_reviewer_approve": all(r["review_status"] == "APPROVE" for r in records),
               "v3_canary_mode": "V3_P2_SAFE_REPAIR_OPT_IN",
               "v41_mode": "P2_EXECUTED_JAVA_EXACTLY_ONCE_GATE",
               "results": records}
    v3 = assess_canary_summary(summary, records)
    if v3["status"] != "V3_P2_CANARY_3_OF_3_PASS":
        summary["overall"] = "FAIL"
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    (root / "v41_assessment.json").write_text(json.dumps({
        "status": "V41_SYNTHETIC_CANDIDATE" if summary["overall"] == "PASS" else "BLOCKED",
        "v3_canary": v3, "production_release_authorized": False,
        "independent_attestation_required": True}, ensure_ascii=False, indent=2), "utf-8")
    return 0 if summary["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
