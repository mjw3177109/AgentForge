#!/usr/bin/env python3
"""V4.1 trusted benchmark wrapper: instruments actual P2, not argument prints."""
from __future__ import annotations
from pathlib import Path
import sys
import run_v18_live_autonomous_benchmark_hardened as hardened


def enable_observation() -> dict[str, bool]:
    original = hardened.base.run
    observed = {"called": False}
    instrumenter = str(Path(__file__).resolve().with_name("v41_instrumented_cli.py"))
    def traced(*args, **kwargs):
        if len(args) > 2 and args[:2] == ("agentforge", "autonomous-live"):
            if "--v3-safe-repair" in args:
                raise RuntimeError("Unexpected existing P2 flag")
            observed["called"] = True
            return original(sys.executable, instrumenter, *args[1:],
                            "--v3-safe-repair", **kwargs)
        return original(*args, **kwargs)
    hardened.base.run = traced
    return observed


def main() -> int:
    observed = enable_observation()
    outcome = hardened.base.main()
    if not observed["called"]:
        raise RuntimeError("V41_P2_WAS_NEVER_INVOKED")
    return outcome

if __name__ == "__main__":
    raise SystemExit(main())
