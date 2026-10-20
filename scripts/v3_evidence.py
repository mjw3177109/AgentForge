#!/usr/bin/env python3
"""V3 P1 optional CLI: collect/sign and independently verify V2.0 evidence.

Never executes live agents, network requests, git operations or project tests.
The attestation key MUST be injected only into an independent trusted job.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from agentforge.evidence_v3 import EvidenceValidationError, attest, collect_v20, verify_v20


def _secret(env_name: str) -> bytes:
    if env_name != "AGENTFORGE_V3_EVIDENCE_KEY":
        raise EvidenceValidationError("Only AGENTFORGE_V3_EVIDENCE_KEY is accepted")
    value = os.getenv(env_name, "")
    if len(value.encode("utf-8")) < 32:
        raise EvidenceValidationError("Independent verification key absent/too short")
    return value.encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline signed evidence for V2.0 acceptance artifacts")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("collect", help="Collect and sign evidence; trusted job only")
    create.add_argument("--artifacts", required=True, type=Path)
    create.add_argument("--profile", required=True, type=Path)
    create.add_argument("--run-id", required=True, type=int)
    create.add_argument("--commit", required=True)
    create.add_argument("--model-id", required=True)
    create.add_argument("--key-id", required=True)
    create.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify", help="Read-only, independently pinned signed evidence verification")
    verify.add_argument("--artifacts", required=True, type=Path)
    verify.add_argument("--profile", required=True, type=Path)
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--expected-run-id", required=True, type=int)
    verify.add_argument("--expected-commit", required=True)
    verify.add_argument("--expected-model-id", required=True)
    verify.add_argument("--expected-key-id", required=True)
    verify.add_argument("--max-age-hours", default=168, type=float)
    args = parser.parse_args(argv)
    try:
        key = _secret("AGENTFORGE_V3_EVIDENCE_KEY")
        if args.command == "collect":
            unsigned = collect_v20(artifact_dir=args.artifacts, run_id=args.run_id,
                                   commit_sha=args.commit, model_id=args.model_id,
                                   trusted_profile=args.profile)
            signed = attest(unsigned, secret=key, key_id=args.key_id)
            out = args.output
            if out.is_symlink():
                raise EvidenceValidationError("Output must not be a symlink")
            # Exclusive create: never overwrite evidence or user data.
            with out.open("x", encoding="utf-8") as handle:
                json.dump(signed, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            print(json.dumps({"status": "COLLECTED", "assessment": unsigned["assessment"]["overall"],
                              "run_id": args.run_id, "output": str(out)}, ensure_ascii=False))
            return 0 if unsigned["assessment"]["overall"] == "PASS" else 2
        if args.manifest.is_symlink() or not args.manifest.is_file():
            raise EvidenceValidationError("Manifest must be a regular, non-symlink file")
        manifest = json.loads(args.manifest.read_text("utf-8"))
        report = verify_v20(manifest, artifact_dir=args.artifacts,
                            trusted_profile=args.profile,
                            expected_run_id=args.expected_run_id,
                            expected_commit_sha=args.expected_commit,
                            expected_model_id=args.expected_model_id,
                            expected_key_id=args.expected_key_id,
                            secret=key, max_age_hours=args.max_age_hours)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "VERIFIED_PASS" else 2
    except (EvidenceValidationError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "issues": [str(exc)]}, ensure_ascii=False), file=sys.stdout)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
