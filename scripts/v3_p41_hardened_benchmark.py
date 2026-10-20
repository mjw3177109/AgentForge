"""Use the V2 hardened fixture but run the REAL opt-in P2 AgentForge runtime.

Only overrides the trusted benchmark's invocation of `agentforge autonomous-live`.
No write permissions, benchmarks, contracts, or review rules are modified.
"""
from __future__ import annotations

import sys
from pathlib import Path

import run_v18_live_autonomous_benchmark_hardened as hardened


EXPECTED_FLAG = "--v3-safe-repair"
CANARY_MARKER = "P41_V3_SAFE_REPAIR_ARG=ENABLED"


def enable_canary() -> dict[str, bool]:
    original = hardened.base.run
    seen = {"invoked": False}

    def run_with_p2(*args, **kwargs):
        if len(args) >= 2 and args[:2] == ("agentforge", "autonomous-live"):
            if EXPECTED_FLAG in args:
                raise RuntimeError("P4.1 flag already present")
            seen["invoked"] = True
            print(CANARY_MARKER, file=sys.stderr, flush=True)
            return original(*args, EXPECTED_FLAG, **kwargs)
        return original(*args, **kwargs)

    hardened.base.run = run_with_p2
    return seen


def main() -> int:
    # The normal V2 hardened path has no P2 flag. Require the new runtime to
    # be present and wired in the installed package before starting the paid run.
    from agentforge.autonomous import AutonomousDevelopmentPipeline
    from agentforge.repair_v3 import SafeRepairRuntime
    import inspect

    if not isinstance(SafeRepairRuntime, type):
        raise RuntimeError("V3_SAFE_REPAIR_NOT_AVAILABLE")
    if "enable_v3_safe_repair" not in inspect.signature(AutonomousDevelopmentPipeline).parameters:
        raise RuntimeError("V3_P2_NOT_INTEGRATED: apply P2 installer on V3 feature branch")
    seen = enable_canary()
    result = hardened.base.main()
    if not seen["invoked"]:
        raise RuntimeError("P4.1 blocked: opt-in command was not invoked")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
