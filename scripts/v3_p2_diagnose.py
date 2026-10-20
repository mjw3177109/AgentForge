#!/usr/bin/env python3
"""Read-only verification failure classifier for AgentForge V3 P2."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from agentforge.coding import VerificationResult
from agentforge.repair_v3 import diagnose_verification


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--log", type=Path, help="Read a Maven/Node/pytest log as failed evidence")
    group.add_argument("--coding-result", type=Path, help="CodingResult JSON with verification array")
    args = p.parse_args()
    if args.log:
        result = [VerificationResult(
            argv=["<offline-log>"], returncode=1, stdout="", stderr=args.log.read_text("utf-8"),
            success=False,
        )]
    else:
        payload = json.loads(args.coding_result.read_text("utf-8"))
        raw = payload.get("verification")
        if not isinstance(raw, list):
            p.error("--coding-result requires a verification result list")
        result = [VerificationResult.model_validate(item) for item in raw]
    d = diagnose_verification(result)
    print(json.dumps({"category": d.category, "retryable": d.retryable,
                      "guidance": d.guidance, "fingerprint": d.fingerprint},
                     ensure_ascii=False, indent=2))
    return 0 if d.category != "NONE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
