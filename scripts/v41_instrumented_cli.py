#!/usr/bin/env python3
"""Trusted in-process observation of SafeRepairRuntime.execute.

This is invoked from the isolated benchmark process, never by a coding Agent.
Writing the trace is outside the generated repository, using exclusive create.
It does not grant any filesystem rights to a model or modify V2/V3 runtime code.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def _trace_destination() -> Path:
    folder = os.environ.get("AGENTFORGE_BENCHMARK_ARTIFACT_DIR", "")
    if not folder or not Path(folder).is_absolute():
        raise RuntimeError("V41_REQUIRES_ABSOLUTE_RUNNER_ARTIFACT_DIR")
    root = Path(folder)
    if root.is_symlink() or root.name not in {f"round_{i:02d}" for i in range(1, 4)}:
        raise RuntimeError("V41_UNSAFE_ARTIFACT_DIRECTORY")
    root.mkdir(parents=True, exist_ok=True)
    if root.resolve() != root:
        raise RuntimeError("V41_ARTIFACT_PATH_IS_NOT_CANONICAL")
    return root / "p2_runtime_proof.json"


def instrument(execute, invocations: list[dict]):
    """Return a bounded decorator for the actual P2 execute method."""
    def tracked(self, task, context_paths, verification, initial_feedback=""):
        result = None
        try:
            result = execute(self, task, context_paths, verification, initial_feedback)
            return result
        finally:
            checks = [{"argv": list(v.argv), "returncode": int(v.returncode),
                       "success": bool(v.success)} for v in self._latest_results]
            invocations.append({
                "task_id": str(task.id), "agent": str(task.assigned_agent),
                "runtime": "SafeRepairRuntime", "status": (result.status if result else "RAISED"),
                "attempts": result.attempts if result else int(self._attempts_seen),
                "verification": checks,
                "diagnoses": [d.category for d in self.diagnoses],
            })
    return tracked


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] != "autonomous-live" or args.count("--v3-safe-repair") != 1:
        raise RuntimeError("V41_REQUIRES_EXACTLY_ONE_P2_OPT_IN")
    trace_path = _trace_destination()
    from agentforge.repair_v3 import SafeRepairRuntime
    from agentforge.cli import main as agentforge_main
    events: list[dict] = []
    original = SafeRepairRuntime.execute
    SafeRepairRuntime.execute = instrument(original, events)
    exit_code = 0
    try:
        sys.argv = ["agentforge", *args]
        try:
            agentforge_main()
        except SystemExit as exc:
            exit_code = int(exc.code) if isinstance(exc.code, int) else 2
    finally:
        SafeRepairRuntime.execute = original
        # Fail closed on trace export failures: never allow a green result
        # without the associated execution proof.
        fd = os.open(trace_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"schema": "agentforge.v41.p2-runtime-proof/1",
                       "invocations": events}, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
