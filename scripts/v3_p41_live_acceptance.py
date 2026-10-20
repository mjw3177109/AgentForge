#!/usr/bin/env python3
"""Real V3 P2 canary using V2 immutable contracts and isolated MySQL/Redis.

Cost-bearing. This runner is never launched by a push event. No PR, merge,
production DB connection, or additional Agent write scopes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from agentforge.acceptance_p41 import assess_canary_summary


def import_v20_runner(repo: Path):
    src = repo / "scripts/run_v20_stability.py"
    if src.is_symlink() or not src.is_file():
        raise ValueError("TRUSTED_V20_RUNNER_MISSING")
    spec = importlib.util.spec_from_file_location("agentforge_p41_v20_runner", src)
    if spec is None or spec.loader is None:
        raise ValueError("TRUSTED_V20_RUNNER_UNLOADABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_round(index: int, root: Path, timeout: int, *, repo: Path, v20: Any) -> dict:
    folder = root / f"round_{index:02d}"
    if folder.exists():
        raise ValueError("Refusing to overwrite an existing round directory")
    env = os.environ.copy()
    env["AGENTFORGE_BENCHMARK_ARTIFACT_DIR"] = str(folder)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, "scripts/v3_p41_hardened_benchmark.py"],
            cwd=repo, text=True, capture_output=True, check=False, timeout=timeout,
            env=env, shell=False,
        )
        stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        code = 124
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "v20_runner_stdout.txt").write_text(stdout, encoding="utf-8")
    (folder / "v20_runner_stderr.txt").write_text(stderr, encoding="utf-8")
    flag = stderr.count("P41_V3_SAFE_REPAIR_ARG=ENABLED") == 1
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError):
        payload = None
    stage, reason = v20.assess_result(payload, code)
    gates = []
    if not flag:
        stage, reason = "p2_not_executed", "Missing P2 opt-in invocation marker"
    if stage == "passed":
        snapshot = folder / "generated-repo"
        if not snapshot.is_dir():
            stage, reason = "snapshot_missing", "Generated repository snapshot is missing"
        else:
            gates = v20.verify_snapshot(snapshot, folder, index)
            failing = next((g for g in gates if g["status"] != "PASS"), None)
            if failing:
                stage, reason = failing["name"], failing.get("error_excerpt") or "Independent gate failed"
    record = {
        "round": index, "status": "PASS" if stage == "passed" else "FAIL",
        "stage": stage, "reason": reason,
        "failure_class": None if stage == "passed" else ("P2_OPT_IN_MISSING" if stage == "p2_not_executed" else v20.classify_failure(stage, reason + "\n" + stderr[-1000:])),
        "benchmark_exit_code": code,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "initial_agents": [r.get("agent") for r in (payload or {}).get("task_runs", [])
                           if "review repair round" not in str(r.get("message", ""))],
        "repair_agents": [r.get("agent") for r in (payload or {}).get("task_runs", [])
                           if "review repair round" in str(r.get("message", ""))],
        "review_status": ((payload or {}).get("review") or {}).get("status"),
        "gates": gates,
        "v3_safe_repair_flag_injected": flag,
    }
    (folder / "v20_result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, choices=[3], default=3)
    parser.add_argument("--round-timeout", type=int, default=1200)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/v30-p41-canary"))
    args = parser.parse_args(argv)
    if not 120 <= args.round_timeout <= 1200:
        parser.error("Timeout must be 120–1200 seconds")
    for key in ("GITHUB_ACTIONS", "AGENTFORGE_LLM_BASE_URL", "AGENTFORGE_LLM_MODEL", "AGENTFORGE_LLM_API_KEY"):
        if not os.environ.get(key) or (key == "GITHUB_ACTIONS" and os.environ[key] != "true"):
            parser.error(f"{key}: required for real-model CI, no silent skipping")
    repo = Path(__file__).resolve().parents[1]
    v20 = import_v20_runner(repo)
    root = args.output_dir.absolute()
    root.mkdir(parents=True, exist_ok=True)
    if (root / "summary.json").exists() or any(root.glob("round_??")):
        parser.error("Evidence output directory must be new/empty; no cross-run reuse")
    records = []
    for i in range(1, 4):
        record = run_round(i, root, args.round_timeout, repo=repo, v20=v20)
        records.append(record)
        print(json.dumps({k: record[k] for k in ("round", "status", "stage", "review_status")}), flush=True)
    passed = sum(x["status"] == "PASS" for x in records)
    summary = {"overall": "PASS" if passed == 3 else "FAIL", "rounds_required": 3,
               "rounds_passed": passed, "all_reviewer_approve": all(x["review_status"] == "APPROVE" for x in records),
               "v3_canary_mode": "V3_P2_SAFE_REPAIR_OPT_IN", "results": records}
    assessment = assess_canary_summary(summary, records)
    if assessment["status"] != "V3_P2_CANARY_3_OF_3_PASS":
        summary["overall"] = "FAIL"
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "v3_p41_assessment.json").write_text(json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"overall": summary["overall"], "rounds_passed": passed,
                      "v3_canary": assessment["status"]}), flush=True)
    return 0 if summary["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
