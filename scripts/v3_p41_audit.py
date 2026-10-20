#!/usr/bin/env python3
"""Read-only P4.1 repo/branch scope audit before cost-bearing DeepSeek.

Checks provenance and P2 opt-in integration; never writes files or permissions.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import importlib.util
import tempfile
from pathlib import Path

import yaml

BASELINE_SHA = "fbb4eabab1b42b26ee1f545c38729dadc68541c5"
IMMUTABLE = (
    "src/agentforge/policy.py", "src/agentforge/workspace.py",
    "src/agentforge/coding.py", "src/agentforge/execution_profiles.py",
    "scripts/run_v20_stability.py", "scripts/run_v18_live_autonomous_benchmark.py",
    "scripts/run_v18_live_autonomous_benchmark_hardened.py",
    "benchmarks/v18_hardened/execution-profiles.yaml",
    "benchmarks/v18_hardened/VerifiedPointsContractTest.java",
    "benchmarks/v18_hardened/backend-contract.test.js",
)
EXPECTED_PREFIXES = ("feature/v3-", "experiment/v3-")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, shell=False, text=True,
                          capture_output=True, timeout=15, check=False)


def validate_p2_exact_diff(repo: Path) -> list[str]:
    """Refuse extra changes to the only two V2 code files P2 may integrate."""
    problems: list[str] = []
    installer = repo / 'scripts/v3_p2_integrate.py'
    if not installer.is_file() or installer.is_symlink():
        return ['P2_INTEGRATION_INSTALLER_MISSING']
    spec = importlib.util.spec_from_file_location('p41_trusted_p2_installer', installer)
    if spec is None or spec.loader is None:
        return ['P2_INTEGRATION_INSTALLER_UNREADABLE']
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='agentforge-p41-audit-') as work:
        shadow = Path(work)
        for rel in ('src/agentforge/autonomous.py', 'src/agentforge/cli.py'):
            original = _git(repo, 'show', f'{BASELINE_SHA}:{rel}')
            if original.returncode:
                problems.append('CANNOT_LOAD_BASELINE_SOURCE:' + rel)
                return problems
            dst = shadow / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(original.stdout, encoding='utf-8')
        try:
            changes = module.plan_integration(shadow)
        except (RuntimeError, ValueError) as exc:
            return ['P2_INSTALLER_STRUCTURAL_MISMATCH:' + str(exc)[:200]]
        for target, (_before, expected) in changes.items():
            rel = target.relative_to(shadow)
            if (repo / rel).read_text('utf-8') != expected:
                problems.append('P2_UNAPPROVED_SOURCE_DELTA:' + str(rel))
    return problems


def audit(repo: Path) -> dict:
    issues = []
    repo = Path(repo).resolve(strict=True)
    branch = _git(repo, "branch", "--show-current").stdout.strip()
    if not branch.startswith(EXPECTED_PREFIXES):
        issues.append("NOT_AN_ISOLATED_V3_BRANCH")
    commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        issues.append("NO_VALID_GIT_HEAD")
    elif _git(repo, "merge-base", "--is-ancestor", BASELINE_SHA, "HEAD").returncode:
        issues.append("V20_REVIEWED_BASELINE_NOT_ANCESTOR")
    for path in IMMUTABLE:
        check = _git(repo, "diff", "--quiet", BASELINE_SHA, "HEAD", "--", path)
        if check.returncode:
            issues.append("TRUSTED_V2_FILE_CHANGED:" + path)
    # Pip editable installs create ignored-by-convention (but not necessarily
    # gitignored) egg-info/ and bytecode. Refuse changed tracked files and
    # unknown untracked files without treating package metadata as source edits.
    state = _git(repo, "status", "--porcelain", "--untracked-files=all")
    for item in state.stdout.splitlines():
        relative = item[3:]
        if item[:2] == '??' and (
            relative.endswith('.pyc') or '/__pycache__/' in relative or
            relative.startswith('__pycache__/') or relative.startswith('.pytest_cache/') or
            '.egg-info/' in relative or '/.pytest_cache/' in relative
        ):
            continue
        issues.append("DIRTY_WORKTREE_BEFORE_ACCEPTANCE:" + relative)
    issues.extend(validate_p2_exact_diff(repo))
    try:
        cli = (repo / "src/agentforge/cli.py").read_text("utf-8")
        autonomous = (repo / "src/agentforge/autonomous.py").read_text("utf-8")
        if '--v3-safe-repair' not in cli or 'enable_v3_safe_repair=args.v3_safe_repair' not in cli:
            issues.append("P2_CLI_NOT_INTEGRATED")
        if 'SafeRepairRuntime if self.enable_v3_safe_repair else LiveCodingRuntime' not in autonomous:
            issues.append("P2_RUNTIME_NOT_OPTED_IN")
        if autonomous.count('SafeRepairRuntime if self.enable_v3_safe_repair else LiveCodingRuntime') != 2:
            issues.append("P2_RUNTIME_SELECTION_COUNT_INVALID")
    except OSError:
        issues.append("P2_BASE_CODE_MISSING")
    try:
        profiles = yaml.safe_load((repo / 'benchmarks/v18_hardened/execution-profiles.yaml').read_text('utf-8'))
        backend = profiles['agents']['backend']
        if backend['write_scope'] != ['server/src/main/**']:
            issues.append('BACKEND_WRITE_CEILING_CHANGED')
        if set(profiles['agents']) != {'database', 'backend', 'miniapp', 'admin'}:
            issues.append('BENCHMARK_AGENT_SET_CHANGED')
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        issues.append('TRUSTED_PROFILE_INVALID')
    return {'status': 'P41_AUDIT_PASS' if not issues else 'BLOCKED',
            'branch': branch, 'commit': commit, 'baseline': BASELINE_SHA,
            'issues': issues, 'automated_merge_authorized': False,
            'production_release_authorized': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    args = parser.parse_args(argv)
    try:
        result = audit(args.repo_root)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {'status': 'BLOCKED', 'issues': [str(exc)],
                  'production_release_authorized': False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'P41_AUDIT_PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
