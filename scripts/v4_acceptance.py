#!/usr/bin/env python3
"""Operator-triggered V4 offline checks. Never calls paid model or production systems."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import subprocess
import sys
import time
from pathlib import Path


def _check(cmd: list[str], repo: Path, timeout: int = 900) -> dict:
    started = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                           timeout=timeout, shell=False, check=False)
        return {'argv': cmd, 'exit_code': p.returncode,
                'seconds': round(time.monotonic() - started, 3),
                'stdout_tail': p.stdout[-2000:], 'stderr_tail': p.stderr[-2000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'argv': cmd, 'exit_code': 124, 'seconds': round(time.monotonic() - started, 3),
                'stdout_tail': '', 'stderr_tail': type(exc).__name__}


def run(repo: Path, *, scope: str, iterations: int) -> dict:
    repo = Path(repo).resolve(strict=True)
    if scope not in ('v4', 'full') or type(iterations) is not int or iterations not in (1, 3):
        raise ValueError('Invalid offline acceptance configuration')
    tests = ['tests/test_v4_control.py', 'tests/test_v4_install.py'] if scope == 'v4' else ['tests']
    steps = []
    for i in range(1, iterations + 1):
        p = _check([sys.executable, '-m', 'pytest', '-q', *tests], repo)
        steps.append({'iteration': i, 'name': 'pytest', **p})
        if p['exit_code'] != 0:
            break
        if scope == 'full':
            v = _check([sys.executable, 'protocol_bundle/scripts/validate_protocol.py'], repo, timeout=120)
            steps.append({'iteration': i, 'name': 'protocol', **v})
            if v['exit_code'] != 0:
                break
    passed = (len(steps) == iterations * (2 if scope == 'full' else 1)
              and all(x['exit_code'] == 0 for x in steps))
    return {'schema': 'agentforge.v4.offline/1', 'status': 'LOCAL_OFFLINE_PASS' if passed else 'FAIL',
            'iterations_required': iterations, 'iterations_passed': iterations if passed else len(set(
                x['iteration'] for x in steps if x['exit_code'] == 0 and
                (scope == 'v4' or x['name'] == 'protocol'))),
            'python_version': f'{sys.version_info.major}.{sys.version_info.minor}',
            'checked_at_utc': datetime.now(timezone.utc).isoformat(),
            'steps': steps, 'live_llm_verified': False, 'github_ci_authenticated': False,
            'production_release_authorized': False}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root', type=Path, default=Path('.'))
    p.add_argument('--scope', choices=['v4', 'full'], default='v4')
    p.add_argument('--iterations', type=int, choices=[1, 3], default=1)
    p.add_argument('--output', type=Path)
    args = p.parse_args(argv)
    try:
        result = run(args.repo_root, scope=args.scope, iterations=args.iterations)
        if args.output:
            if args.output.is_symlink() or not args.output.parent.is_dir():
                raise ValueError('Output must be a non-symlink in existing directory')
            if args.output.exists():
                raise ValueError('Refuse overwrite of existing acceptance report')
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'LOCAL_OFFLINE_PASS' else 2
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc),
                          'production_release_authorized': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
