"""V4 gate: require independent P1 signature AND live V3 P2 canary evidence.

This is NOT a proof of production behavior, service-level exactly-once credit,
or permission to merge/deploy. It ONLY authenticates one synthetic live fixture.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .core import ControlDenied, canonical, _guard_file


def verify_p41_evidence(*, artifact_dir: Path, manifest: Path, profile: Path,
                        run_id: int, commit_sha: str, model_id: str,
                        key_id: str, secret: bytes) -> dict[str, Any]:
    from agentforge.acceptance_v3 import validate_attested_run
    from agentforge.acceptance_p41 import assess_canary_summary

    blocked = {'status': 'BLOCKED', 'independent_verified': False,
               'production_release_authorized': False, 'auto_merge_authorized': False}
    if type(run_id) is not int or run_id < 1:
        return {**blocked, 'reason': 'INVALID_RUN_ID'}
    try:
        artifacts = Path(artifact_dir).resolve(strict=True)
        trusted_profile = Path(profile).resolve(strict=True)
        envelope = Path(manifest).resolve(strict=True)
        if not artifacts.is_dir() or not envelope.is_file() or not trusted_profile.is_file():
            raise ControlDenied('Missing evidence or trusted profile')
        # Trust root and signer must be provided independently of generated data.
        if len(secret) < 32:
            raise ControlDenied('Independent verification key missing')
        attested = validate_attested_run(
            manifest=envelope, artifacts=artifacts, trusted_profile=trusted_profile,
            expected_run_id=run_id, expected_commit=commit_sha,
            expected_model=model_id, expected_key_id=key_id,
            secret=secret,
        )
        if attested.get('status') != 'INDEPENDENT_LIVE_3_OF_3_VERIFIED':
            return {**blocked, 'reason': 'P1_INDEPENDENT_EVIDENCE_REJECTED',
                    'details': attested.get('issues', [])}
        # Independent V3 opt-in check cannot be satisfied by V2-only PASS.
        def load(rel: str) -> dict:
            path = _guard_file(artifacts, rel)
            if path.stat().st_size > 2_000_000:
                raise ControlDenied('Oversized canary evidence')
            data = json.loads(path.read_text('utf-8'))
            if not isinstance(data, dict):
                raise ControlDenied('Canary data must be object')
            return data
        summary = load('summary.json')
        rounds = [load(f'round_{i:02d}/v20_result.json') for i in (1, 2, 3)]
        canary = assess_canary_summary(summary, rounds)
        if canary.get('status') != 'V3_P2_CANARY_3_OF_3_PASS':
            return {**blocked, 'reason': 'V3_P2_CANARY_REJECTED',
                    'details': canary.get('issues', [])}
        digest = hashlib.sha256(envelope.read_bytes() + b'\0' + canonical(summary)).hexdigest()
        return {'status': 'SYNTHETIC_V3_P2_EVIDENCE_VERIFIED', 'independent_verified': True,
                'evidence_hash': digest, 'run_id': run_id, 'commit_sha': commit_sha,
                'production_release_authorized': False, 'auto_merge_authorized': False,
                'note': 'Synthetic fixture only; Django, production payments, and release readiness unverified'}
    except (OSError, ControlDenied, ValueError, TypeError, KeyError) as exc:
        return {**blocked, 'reason': 'UNTRUSTED_EVIDENCE_INPUT:' + type(exc).__name__}
