#!/usr/bin/env python3
"""AgentForge V3 P3 memory CLI: local, advisory-only, no agent execution."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from agentforge.memory_v3 import MemorySafetyError, MemoryStore, trusted_profile_hash


def read_json_safe(path: Path) -> dict:
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise MemorySafetyError("Input path contains symlink")
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise MemorySafetyError("JSON input missing or too large")
    obj = json.loads(path.read_text("utf-8"))
    if not isinstance(obj, dict):
        raise MemorySafetyError("JSON input must be an object")
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True,
                        help="Dedicated local SQLite path OUTSIDE the target project")
    cmds = parser.add_subparsers(dest="action", required=True)
    cmds.add_parser("init", help="Explicitly initialize a new local memory store")
    for name in ("observe", "recommend", "predeclare", "import-run", "history"):
        cmd = cmds.add_parser(name)
        cmd.add_argument("--project", required=True)
        if name in {"observe", "recommend", "predeclare", "import-run"}:
            cmd.add_argument("--profile", type=Path, required=True)
        if name in {"observe", "recommend"}:
            cmd.add_argument("--diagnosis", type=Path, required=True,
                             help="P2 v3_p2_diagnose.py JSON, NOT raw logs")
        if name == "observe":
            cmd.add_argument("--source-id", required=True,
                             help="Non-secret unique diagnostic source label")
        if name == "predeclare":
            cmd.add_argument("--fingerprint", required=True)
            cmd.add_argument("--strategy-id", required=True)
            cmd.add_argument("--run-id", type=int, required=True)
            cmd.add_argument("--commit", required=True)
        if name == "import-run":
            cmd.add_argument("--manifest", required=True, type=Path)
            cmd.add_argument("--artifacts", required=True, type=Path)
            cmd.add_argument("--run-id", required=True, type=int)
            cmd.add_argument("--commit", required=True)
            cmd.add_argument("--model", required=True)
            cmd.add_argument("--key-id", required=True)
            cmd.add_argument("--max-age-hours", type=float, default=168.0)
        if name in {"history", "recommend"}:
            cmd.add_argument("--limit", type=int, default=20 if name == "history" else 3)
    args = parser.parse_args(argv)
    try:
        store = MemoryStore(args.db)
        if args.action == "init":
            store.initialize()
            out = {"status": "INITIALIZED", "db": str(store.path)}
        elif args.action == "history":
            out = store.history(project=args.project, limit=args.limit)
        elif args.action == "import-run":
            secret = os.environ.get("AGENTFORGE_V3_EVIDENCE_KEY", "").encode("utf-8")
            if len(secret) < 32:
                raise MemorySafetyError("Independent attestation key is required")
            out = store.import_attested_run(
                project=args.project, envelope=read_json_safe(args.manifest),
                artifact_dir=args.artifacts, trusted_profile=args.profile,
                expected_run_id=args.run_id, expected_commit_sha=args.commit,
                expected_model_id=args.model, expected_key_id=args.key_id,
                secret=secret, max_age_hours=args.max_age_hours,
            )
        else:
            profile_hash = trusted_profile_hash(args.profile)
            if args.action == "observe":
                out = store.observe_diagnosis(
                    project=args.project, profile_sha256=profile_hash,
                    diagnosis=read_json_safe(args.diagnosis), source_id=args.source_id)
            elif args.action == "recommend":
                out = store.recommend(
                    project=args.project, profile_sha256=profile_hash,
                    diagnosis=read_json_safe(args.diagnosis), limit=args.limit)
            else:
                out = store.predeclare_trial(
                    project=args.project, profile_sha256=profile_hash,
                    run_id=args.run_id, commit_sha=args.commit,
                    fingerprint=args.fingerprint, strategy_id=args.strategy_id)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        if out.get("status") in {"IMPORTED_FAIL", "BLOCKED_FOR_AUTOREPAIR", "NO_SAFE_RECOMMENDATION"}:
            return 2  # Importing a historical failure must never green-light a CI gate.
        return 0
    except (MemorySafetyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
