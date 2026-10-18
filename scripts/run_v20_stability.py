"""V2.0 acceptance: independent live rounds + executable evidence gates.

Runs only against the isolated GitHub Actions MySQL/Redis service containers.
No production deployment, Git push, or automatic merge is performed here.
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REQUIRED_AGENTS = ("database", "backend", "miniapp", "admin")
CONTRACT_TESTS = (
    "verification/database-contract.test.js",
    "verification/backend-contract.test.js",
    "miniapp/tests/points.test.js",
    "admin-web/tests/points-ledger-contract.test.js",
)


def assess_result(payload: dict[str, Any] | None, exit_code: int) -> tuple[str, str]:
    """Return (failure_stage, reason); 'passed' means protocol-level acceptance."""
    if not isinstance(payload, dict):
        return "transport_or_protocol", "Benchmark produced no valid JSON result"
    if exit_code != 0:
        if payload.get("status") == "REVIEW_CHANGES":
            return "review", "Reviewer rejected the final deliverable"
        if payload.get("status") == "BLOCKED":
            blocked = next(
                (item for item in reversed(payload.get("task_runs") or [])
                 if item.get("status") == "BLOCKED"), {}
            )
            return "agent_blocked", (
                str(payload.get("message", "Agent blocked"))
                + ": " + str(blocked.get("message", "No task-level reason recorded"))
            )
        return "execution", f"Benchmark exit={exit_code}: {str(payload.get('message', ''))[:400]}"
    if payload.get("status") != "SUCCESS":
        return "orchestration", f"Unexpected final status: {payload.get('status')}"
    review = payload.get("review") or {}
    if review.get("status") != "APPROVE":
        return "review", f"Final Reviewer status: {review.get('status')}"
    runs = payload.get("task_runs")
    if not isinstance(runs, list):
        return "task_records", "No structured task run evidence"
    first = {}
    repairs = {}
    for record in runs:
        agent = record.get("agent")
        if agent not in REQUIRED_AGENTS or record.get("status") != "SUCCESS":
            return "task_records", f"Unknown or failed task execution: {record.get('task_id')}"
        if not record.get("commit"):
            return "task_records", f"Missing committed change for {record.get('task_id')}"
        if "review repair round" in str(record.get("message", "")):
            repairs[record.get("task_id")] = repairs.get(record.get("task_id"), 0) + 1
        else:
            first[agent] = first.get(agent, 0) + 1
    if any(first.get(a) != 1 for a in REQUIRED_AGENTS):
        return "task_records", f"Expected exactly one initial pass per agent; observed {first}"
    if any(n > 2 for n in repairs.values()):
        return "repair_budget", f"Per-task repair budget exceeded: {repairs}"
    if payload.get("pr_url"):
        return "release_safety", "Acceptance run unexpectedly published a pull request"
    return "passed", "Four agents, bounded repairs and Reviewer APPROVE"


def classify_failure(stage: str, details: str) -> str:
    low = details.lower()
    if stage == "agent_blocked" and ("write scope" in low or "write_scope" in low) and (
        "src/test/" in low or "tests/" in low or "junit" in low
    ):
        return "VERIFICATION_SCOPE_GAP"
    if "429" in low or "rate limit" in low:
        return "LLM_RATE_LIMIT"
    if "timed out" in low or "timeout" in low:
        return "TIMEOUT"
    if "validationerror" in low or "jsondecodeerror" in low:
        return "LLM_SCHEMA"
    if "policydenied" in low or "scope" in low and "denied" in low:
        return "SECURITY_POLICY"
    if stage == "review":
        return "REVIEW_SEMANTICS"
    if stage.startswith("mysql"):
        return "MYSQL_CONTRACT"
    if stage.startswith("node") or stage == "npm_vite":
        return "NODE_CONTRACT"
    if stage == "maven":
        return "MAVEN_CONTRACT"
    if stage == "release_safety":
        return "UNSAFE_RELEASE"
    return "FRAMEWORK_OR_ENVIRONMENT"


def _command(argv: list[str], cwd: Path, seconds: int, *, stdin: str | None = None,
             env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        p = subprocess.run(
            argv, cwd=cwd, text=True, capture_output=True, input=stdin,
            timeout=seconds, check=False, env=env,
        )
        return {
            "exit_code": p.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "stdout": p.stdout[-12000:],
            "stderr": p.stderr[-12000:],
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "elapsed_seconds": round(time.monotonic() - started, 2),
                "stdout": "", "stderr": f"command timed out after {seconds} seconds"}
    except OSError as exc:
        return {"exit_code": 127, "elapsed_seconds": round(time.monotonic() - started, 2),
                "stdout": "", "stderr": str(exc)}


def _gate(folder: Path, name: str, argv: list[str], cwd: Path, seconds: int,
          *, stdin: str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    result = _command(argv, cwd, seconds, stdin=stdin, env=env)
    (folder / f"{name}.log").write_text(
        f"exit_code={result['exit_code']}\nstdout:\n{result['stdout']}\nstderr:\n{result['stderr']}\n",
        encoding="utf-8",
    )
    return {"name": name, "exit_code": result["exit_code"],
            "elapsed_seconds": result["elapsed_seconds"],
            "status": "PASS" if result["exit_code"] == 0 else "FAIL",
            "error_excerpt": result["stderr"][-500:] if result["exit_code"] else ""}


def verify_snapshot(snapshot: Path, folder: Path, index: int) -> list[dict[str, Any]]:
    """Re-execute immutable contracts, Maven, Vite and schema against the final output."""
    checks = []
    for filename in CONTRACT_TESTS:
        name = "node_" + Path(filename).stem.replace(".", "_")
        if not (snapshot / filename).is_file():
            return checks + [{"name": name, "status": "FAIL", "exit_code": 2,
                              "error_excerpt": f"Missing immutable test {filename}"}]
        checks.append(_gate(folder, name, ["node", "--test", filename], snapshot, 90))
        if checks[-1]["status"] != "PASS":
            return checks

    checks.append(_gate(folder, "maven", ["mvn", "-q", "-f", "server/pom.xml", "test"],
                        snapshot, 360))
    if checks[-1]["status"] != "PASS":
        return checks
    admin = snapshot / "admin-web"
    checks.append(_gate(folder, "npm_install",
                        ["npm", "install", "--no-audit", "--no-fund"], admin, 360))
    if checks[-1]["status"] != "PASS":
        return checks
    checks.append(_gate(folder, "npm_vite", ["npm", "run", "build"], admin, 180))
    if checks[-1]["status"] != "PASS":
        return checks

    migration = snapshot / "database/migrations/V980100__points.sql"
    if not migration.is_file():
        return checks + [{"name": "mysql_schema", "status": "FAIL", "exit_code": 2,
                          "error_excerpt": "Missing required migration"}]
    schema = f"agentforge_v20_gate_{os.getpid()}_{index:02d}"
    mysql = ["mysql", "--protocol=TCP", "-h127.0.0.1", "-P3306", "-uroot", "-N"]
    mysql_env = os.environ.copy()
    mysql_env["MYSQL_PWD"] = os.getenv("AGENTFORGE_V20_MYSQL_PASSWORD", "")
    try:
        checks.append(_gate(folder, "mysql_create", mysql, snapshot, 30,
                            stdin=f"CREATE DATABASE `{schema}`;\n", env=mysql_env))
        if checks[-1]["status"] != "PASS":
            return checks
        sql = migration.read_text(encoding="utf-8")
        result = _command(mysql, snapshot, 90, env=mysql_env, stdin=(
            f"USE `{schema}`;\n{sql}\n"
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA='{schema}' ORDER BY TABLE_NAME;\n"
        ))
        names = set(result["stdout"].splitlines())
        ok = result["exit_code"] == 0 and {"points_account", "points_ledger"}.issubset(names)
        (folder / "mysql_schema.log").write_text(
            f"exit_code={result['exit_code']}\n{result['stdout']}\n{result['stderr']}\n",
            encoding="utf-8",
        )
        checks.append({"name": "mysql_schema", "status": "PASS" if ok else "FAIL",
                       "exit_code": result["exit_code"] if not ok and result["exit_code"] else (0 if ok else 2),
                       "elapsed_seconds": result["elapsed_seconds"],
                       "error_excerpt": "" if ok else "Schema did not create both contract tables"})
        if ok:
            # Exercise the real MySQL uniqueness constraint under concurrent
            # connections, not just a text grep of the generated SQL.
            account_id = 98010000 + index
            event_key = f"AF-V20-SAME-BUSINESS-NO-{index:02d}"
            seed = _command(mysql, snapshot, 30, env=mysql_env, stdin=(
                f"INSERT INTO `{schema}`.points_account "
                "(user_id, balance_points, created_at, updated_at) "
                f"VALUES ({account_id}, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);\n"
            ))
            if seed["exit_code"] == 0:
                def concurrent_insert(row_id: int) -> dict[str, Any]:
                    return _command(mysql, snapshot, 30, env=mysql_env, stdin=(
                        f"INSERT INTO `{schema}`.points_ledger "
                        "(id, user_id, business_no, entry_type, points_delta, "
                        "order_paid_amount_yuan, created_at) "
                        f"VALUES ({row_id}, {account_id}, '{event_key}', 'EARN', "
                        "1, 1.00, CURRENT_TIMESTAMP);\n"
                    ))
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(concurrent_insert, account_id * 10 + i)
                               for i in (1, 2)]
                    insert_results = [future.result() for future in futures]
                count_result = _command(mysql, snapshot, 30, env=mysql_env, stdin=(
                    f"SELECT COUNT(*) FROM `{schema}`.points_ledger "
                    f"WHERE business_no='{event_key}';\n"
                ))
                successful = sum(r["exit_code"] == 0 for r in insert_results)
                failed = [r for r in insert_results if r["exit_code"] != 0]
                valid = (
                    successful == 1 and len(failed) == 1
                    and ("Duplicate entry" in failed[0]["stderr"]
                         or "1062" in failed[0]["stderr"])
                    and count_result["exit_code"] == 0
                    and count_result["stdout"].strip() == "1"
                )
            else:
                insert_results = []
                count_result = {"exit_code": 1, "stdout": "", "stderr": "account seed failed"}
                valid = False
            (folder / "mysql_concurrent_ledger_uniqueness.log").write_text(
                json.dumps({"seed": seed, "inserts": insert_results,
                            "count": count_result}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            checks.append({
                "name": "mysql_concurrent_ledger_uniqueness",
                "status": "PASS" if valid else "FAIL",
                "exit_code": 0 if valid else 2,
                "error_excerpt": "" if valid else (
                    "Two concurrent inserts with the same business_no did not "
                    "produce exactly one committed ledger row and one duplicate-key rejection."
                ),
            })
    finally:
        _gate(folder, "mysql_cleanup", mysql, snapshot, 30,
              stdin=f"DROP DATABASE IF EXISTS `{schema}`;\n", env=mysql_env)
    return checks


def run_round(index: int, root: Path, timeout: int) -> dict[str, Any]:
    folder = root / f"round_{index:02d}"
    env = os.environ.copy()
    env["AGENTFORGE_BENCHMARK_ARTIFACT_DIR"] = str(folder)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, "scripts/run_v18_live_autonomous_benchmark_hardened.py"],
            text=True, capture_output=True, check=False, timeout=timeout, env=env,
        )
        stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        code = 124
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "v20_runner_stdout.txt").write_text(stdout, encoding="utf-8")
    (folder / "v20_runner_stderr.txt").write_text(stderr, encoding="utf-8")
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        payload = None
    stage, reason = assess_result(payload, code)
    gates = []
    if stage == "passed":
        snapshot = folder / "generated-repo"
        if not snapshot.is_dir():
            stage, reason = "snapshot_missing", "No generated-repo evidence was uploaded"
        else:
            gates = verify_snapshot(snapshot, folder, index)
            bad = next((x for x in gates if x["status"] != "PASS"), None)
            if bad:
                stage, reason = bad["name"], bad.get("error_excerpt") or "Independent gate failed"
    record = {
        "round": index, "status": "PASS" if stage == "passed" else "FAIL",
        "stage": stage, "reason": reason,
        "failure_class": None if stage == "passed" else classify_failure(stage, reason + "\n" + stderr[-1000:]),
        "benchmark_exit_code": code,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "initial_agents": [x.get("agent") for x in (payload or {}).get("task_runs", [])
                           if "review repair round" not in str(x.get("message", ""))],
        "repair_agents": [x.get("agent") for x in (payload or {}).get("task_runs", [])
                          if "review repair round" in str(x.get("message", ""))],
        "review_status": ((payload or {}).get("review") or {}).get("status"),
        "gates": gates,
    }
    (folder / "v20_result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentForge V2.0 stability acceptance gate")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--round-timeout", type=int, default=1200)
    parser.add_argument("--output-dir", default="artifacts/v20-stability")
    args = parser.parse_args()
    if not 1 <= args.rounds <= 5:
        parser.error("--rounds must be between 1 and 5")
    if not os.getenv("GITHUB_ACTIONS") == "true":
        parser.error("This gate requires isolated GitHub Actions services (GITHUB_ACTIONS=true)")
    for key in ("AGENTFORGE_LLM_BASE_URL", "AGENTFORGE_LLM_MODEL", "AGENTFORGE_LLM_API_KEY"):
        if not os.environ.get(key):
            parser.error(f"{key} missing: never classify a skipped real-model test as PASS")
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rounds = []
    for index in range(1, args.rounds + 1):
        print(f"[V2.0] starting independent live round {index}/{args.rounds}", flush=True)
        result = run_round(index, root, args.round_timeout)
        rounds.append(result)
        print(json.dumps({k: result[k] for k in
                          ("round", "status", "stage", "failure_class", "review_status")},
                         ensure_ascii=False), flush=True)
    passed = sum(x["status"] == "PASS" for x in rounds)
    final = {"overall": "PASS" if passed == args.rounds else "FAIL",
             "rounds_required": args.rounds, "rounds_passed": passed,
             "all_reviewer_approve": all(x["review_status"] == "APPROVE" for x in rounds),
             "results": rounds}
    (root / "summary.json").write_text(json.dumps(final, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(json.dumps({k: v for k, v in final.items() if k != "results"},
                     ensure_ascii=False), flush=True)
    return 0 if final["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
