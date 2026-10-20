#!/usr/bin/env python3
"""Offline, read-only V3 task governance prototype.

Example: python scripts/v3_preflight.py --repo-root . \\
 --profiles benchmarks/v18_hardened/execution-profiles.yaml \\
 --agent backend --task examples/v3_preflight_request.json
"""
import argparse
import json
import sys
from pathlib import Path

from agentforge.execution_profiles import load_execution_profiles
from agentforge.governance import ProposedChange, assess


def _contained_file(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Policy/task file must be a relative path inside repo")
    joined = root / candidate
    if any(p.is_symlink() for p in [root / Path(*candidate.parts[:i]) for i in range(1, len(candidate.parts) + 1)]):
        raise ValueError("Policy/task files may not be symlinks")
    resolved = joined.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("File escapes repository root")
    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="V3 read-only governance preflight")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--profiles", required=True, help="Trusted V2 execution profiles in repository")
    parser.add_argument("--agent", required=True, help="Agent name from trusted profiles")
    parser.add_argument("--task", required=True, help="JSON containing task_id and proposed_paths; no policy overrides")
    args = parser.parse_args(argv)
    try:
        root = Path(args.repo_root).resolve(strict=True)
        profiles = load_execution_profiles(_contained_file(root, args.profiles)).profiles
        if args.agent not in profiles:
            raise ValueError(f"Unknown agent in trusted profiles: {args.agent}")
        task_data = json.loads(_contained_file(root, args.task).read_text("utf-8"))
        if not isinstance(task_data, dict) or set(task_data) != {"task_id", "proposed_paths"}:
            raise ValueError("Task JSON accepts exactly task_id and proposed_paths; task-supplied scopes forbidden")
        paths = task_data["proposed_paths"]
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ValueError("proposed_paths must be a list of strings")
        result = assess(repo_root=root, task=ProposedChange(task_data["task_id"], tuple(paths)), agent=args.agent, trusted_profile=profiles[args.agent])
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.status == "SCOPE_PRECHECK_OK" else 2
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "verification": "NOT_EXECUTED"}, ensure_ascii=False), file=sys.stdout)
        return 2


if __name__ == "__main__":
    sys.exit(main())
