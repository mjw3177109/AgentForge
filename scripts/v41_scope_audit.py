#!/usr/bin/env python3
"""Read-only V4.1 branch ancestry and protected security-boundary audit."""
from __future__ import annotations
import json
from pathlib import Path
import re
import subprocess

BASELINE = "fbb4eabab1b42b26ee1f545c38729dadc68541c5"
PROTECTED = (
    "src/agentforge/policy.py", "src/agentforge/workspace.py",
    "src/agentforge/execution_profiles.py",
    "benchmarks/v18_hardened/execution-profiles.yaml",
    "scripts/run_v20_stability.py",
)


def _git(repo: Path, *args: str):
    return subprocess.run(["git", *args], cwd=repo, check=False,
                          capture_output=True, text=True, timeout=30)


def audit(repo: Path) -> dict:
    issues = []
    branch = _git(repo, "branch", "--show-current")
    if branch.returncode != 0 or not branch.stdout.strip().startswith("feature/v4-"):
        issues.append("V41_REQUIRES_FEATURE_V4_BRANCH")
    base = _git(repo, "merge-base", "--is-ancestor", BASELINE, "HEAD")
    if base.returncode != 0:
        issues.append("TRUSTED_V20_BASELINE_NOT_ANCESTOR")
    protected = _git(repo, "diff", "--name-only", BASELINE, "HEAD", "--", *PROTECTED)
    if protected.returncode != 0 or protected.stdout.strip():
        issues.append("PROTECTED_POLICY_OR_VERIFIER_CHANGED")
    module = repo / "src/agentforge/autonomous.py"
    cli = repo / "src/agentforge/cli.py"
    try:
        content = module.read_text("utf-8")
        command = cli.read_text("utf-8")
        if ("enable_v3_safe_repair" not in content or "SafeRepairRuntime" not in content
                or "--v3-safe-repair" not in command):
            issues.append("P2_OPT_IN_INTEGRATION_MISSING")
        source = repo / "benchmarks/v41_trusted/TrustedPointsExactlyOnceTest.java"
        if source.is_symlink() or not source.is_file() or source.stat().st_size < 3000:
            issues.append("TRUSTED_JAVA_BEHAVIOR_FIXTURE_MISSING")
    except OSError:
        issues.append("TRUSTED_SOURCES_MISSING")
    return {"status": "PASS" if not issues else "BLOCKED", "issues": issues,
            "protected_paths": list(PROTECTED), "release_authorized": False}


def main():
    result = audit(Path(__file__).resolve().parents[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
