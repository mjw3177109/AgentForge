#!/usr/bin/env python3
"""AgentForge V3 P4 offline/gated acceptance CLI. No GitHub mutations.

inspect: files are present (NOT integrated or independently accepted).
history: read historical unsigned V2 evidence for diagnostic purposes only.
verify: require trusted P1 HMAC and externally pinned Run/commit/model/profile.
offline: run fixed test suite and protocol checks with local Python.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from agentforge.acceptance_v3 import (
    inspect_components, inspect_v20_history, python_minor,
    validate_attested_run,
)


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _git_commit(root: Path) -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, shell=False,
                            capture_output=True, text=True, timeout=15, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def fixed_offline_suite(repo: Path, *, iterations: int, scope: str,
                        timeout_seconds: int = 600) -> dict:
    if iterations not in (1, 3) or scope not in ("v3-smoke", "full"):
        raise ValueError("Only 1 or 3 iterations and fixed scopes are supported")
    if timeout_seconds < 10 or timeout_seconds > 1800:
        raise ValueError("Invalid test timeout")
    repo = Path(repo).resolve(strict=True)
    tests = ["tests/test_v3_preflight.py", "tests/test_v3_evidence.py",
             "tests/test_v3_repair.py", "tests/test_v3_p2_installer.py",
             "tests/test_v3_memory.py", "tests/test_v3_p4_acceptance.py"]
    for file in tests + (["protocol_bundle/scripts/validate_protocol.py"] if scope == "full" else []):
        f = repo / file
        if f.is_symlink() or not f.is_file() or not f.resolve().is_relative_to(repo):
            return {"status": "BLOCKED", "issues": ["MISSING_OR_UNSAFE_TEST:" + file]}
    # Environment may contain project-specific test configuration, but no shell interpolation.
    commands = [[sys.executable, "-m", "pytest", "-q", "-ra", *(tests if scope == "v3-smoke" else [])]]
    if scope == "full":
        commands.append([sys.executable, "protocol_bundle/scripts/validate_protocol.py"])
    results = []
    successful = 0
    for iteration in range(1, iterations + 1):
        checks = []
        for argv in commands:
            try:
                result = subprocess.run(argv, cwd=repo, shell=False,
                                        capture_output=True, text=True,
                                        timeout=timeout_seconds, check=False)
                output = (result.stdout + "\n" + result.stderr)[-20000:]
                # A skipped/xfailed suite is not silently promoted to complete acceptance.
                incomplete = bool(re.search(r"\b[1-9]\d*\s+(?:skipped|xfailed|xpassed)\b", output))
                pytest_count = re.search(r"\b(\d+)\s+passed\b", output)
                passed = (result.returncode == 0 and not incomplete and
                          (pytest_count is not None and int(pytest_count.group(1)) > 0 if "pytest" in argv else True))
                checks.append({"command": argv[1:], "exit_code": result.returncode,
                               "status": "PASS" if passed else "FAIL",
                               "pytest_passed": int(pytest_count.group(1)) if pytest_count else None,
                               "output_tail": output[-1500:]})
            except (subprocess.TimeoutExpired, OSError) as exc:
                checks.append({"command": argv[1:], "exit_code": 124,
                               "status": "FAIL", "reason": type(exc).__name__})
            if checks[-1]["status"] != "PASS":
                break
        iteration_pass = len(checks) == len(commands) and all(x["status"] == "PASS" for x in checks)
        results.append({"iteration": iteration, "checks": checks,
                        "status": "PASS" if iteration_pass else "FAIL"})
        if not iteration_pass:
            break
        successful += 1
    commit = _git_commit(repo)
    return {"status": "OFFLINE_SUITE_PASS" if successful == iterations else "OFFLINE_SUITE_FAIL",
            "scope": scope, "python_minor": python_minor(), "git_commit": commit,
            "iterations_required": iterations, "iterations_passed": successful,
            "results": results, "source": "LOCAL_SUBPROCESS_RUN_NOT_SIGNED",
            "production_release_authorized": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--repo-root", type=Path, default=Path("."))
    history = commands.add_parser("history")
    history.add_argument("--artifacts", type=Path, required=True)
    offline = commands.add_parser("offline")
    offline.add_argument("--repo-root", type=Path, default=Path("."))
    offline.add_argument("--scope", choices=("v3-smoke", "full"), default="v3-smoke")
    offline.add_argument("--iterations", type=int, choices=(1, 3), default=1)
    offline.add_argument("--output", type=Path)
    verify = commands.add_parser("verify")
    for flag in ("artifacts", "profile", "manifest"):
        verify.add_argument("--" + flag, type=Path, required=True)
    verify.add_argument("--expected-run-id", type=int, required=True)
    verify.add_argument("--expected-commit", required=True)
    verify.add_argument("--expected-model", required=True)
    verify.add_argument("--expected-key-id", required=True)
    verify.add_argument("--max-age-hours", type=float, default=168)
    args = parser.parse_args(argv)
    try:
        if args.mode == "inspect":
            report = inspect_components(args.repo_root)
        elif args.mode == "history":
            report = inspect_v20_history(args.artifacts)
        elif args.mode == "offline":
            report = fixed_offline_suite(args.repo_root, iterations=args.iterations,
                                         scope=args.scope)
            if args.output:
                target = args.output.absolute()
                if target.is_symlink() or target.exists() or not target.parent.is_dir():
                    raise ValueError("Output must not exist or be symlink")
                with target.open("x", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
                    f.write("\n")
        else:
            key = os.environ.get("AGENTFORGE_V3_EVIDENCE_KEY", "").encode("utf-8")
            if len(key) < 32:
                raise ValueError("Independent P1 evidence key missing/too short")
            report = validate_attested_run(
                manifest=args.manifest, artifacts=args.artifacts,
                trusted_profile=args.profile, expected_run_id=args.expected_run_id,
                expected_commit=args.expected_commit, expected_model=args.expected_model,
                expected_key_id=args.expected_key_id, secret=key,
                max_age_hours=args.max_age_hours)
        _print(report)
        return 0 if report["status"] in {"COMPONENTS_PRESENT_NOT_VERIFIED",
                                          "OFFLINE_SUITE_PASS",
                                          "INDEPENDENT_LIVE_3_OF_3_VERIFIED"} else 2
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        _print({"status": "BLOCKED", "issues": [str(exc)],
                "production_release_authorized": False})
        return 2


if __name__ == "__main__":
    sys.exit(main())
