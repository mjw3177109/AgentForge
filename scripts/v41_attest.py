#!/usr/bin/env python3
"""Sign and verify V4.1 in a separate, trusted CI job (never the model job)."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from agentforge.v41.attestation import create_attestation, verify_attestation


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("collect", "verify"):
        target = sub.add_parser(name)
        for field in ("artifacts", "p1-manifest", "profile", "output" if name == "collect" else "manifest"):
            target.add_argument("--" + field, type=Path, required=True)
        target.add_argument("--run-id", type=int, required=True)
        target.add_argument("--commit", required=True)
        target.add_argument("--model", required=True)
    args = p.parse_args(argv)
    p1_key = os.getenv("AGENTFORGE_V3_EVIDENCE_KEY", "").encode()
    key = os.getenv("AGENTFORGE_V41_ATTEST_KEY", "").encode()
    if len(p1_key) < 32 or len(key) < 32:
        print(json.dumps({"status": "BLOCKED", "reason": "INDEPENDENT_KEYS_REQUIRED"}))
        return 2
    if args.command == "collect":
        try:
            signed = create_attestation(args.artifacts, args.p1_manifest, args.profile,
                                        run_id=args.run_id, commit=args.commit,
                                        model=args.model, p1_key=p1_key, v41_key=key)
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(signed, output, ensure_ascii=False, indent=2)
            print(json.dumps({"status": "V41_SIGNED", "run_id": args.run_id}))
            return 0
        except (ValueError, OSError) as exc:
            print(json.dumps({"status": "BLOCKED", "reason": str(exc)[:400]}))
            return 2
    try:
        if args.manifest.is_symlink() or not args.manifest.is_file():
            raise ValueError("V41_MANIFEST_MISSING")
        value = json.loads(args.manifest.read_text("utf-8"))
        result = verify_attestation(value, args.artifacts, args.p1_manifest, args.profile,
                                    run_id=args.run_id, commit=args.commit,
                                    model=args.model, p1_key=p1_key, v41_key=key)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        result = {"status": "BLOCKED", "reason": str(exc)[:400]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "V41_SYNTHETIC_INDEPENDENTLY_ATTESTED" else 2

if __name__ == "__main__":
    raise SystemExit(main())
