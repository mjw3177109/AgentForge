#!/usr/bin/env python3
"""Second independent gate: attested V2 contracts PLUS actual V3 P2 canary mode.

Not a production-release approval. Trust relies on the verifier checkout and
HMAC key being isolated from the model-running job.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agentforge.acceptance_p41 import assess_canary_summary
from agentforge.acceptance_v3 import validate_attested_run


def verify(artifacts: Path, profile: Path, manifest: Path, *, run_id: int,
           commit: str, model: str, key_id: str, secret: bytes) -> dict:
    independent = validate_attested_run(
        manifest=manifest, artifacts=artifacts, trusted_profile=profile,
        expected_run_id=run_id, expected_commit=commit, expected_model=model,
        expected_key_id=key_id, secret=secret,
    )
    if independent.get('status') != 'INDEPENDENT_LIVE_3_OF_3_VERIFIED':
        return {'status': 'BLOCKED', 'reason': 'INDEPENDENT_P1_VERIFICATION_FAILED',
                'evidence': independent, 'production_release_authorized': False}
    try:
        summary = json.loads((artifacts / 'summary.json').read_text('utf-8'))
        rounds = [json.loads((artifacts / f'round_{i:02d}' / 'v20_result.json').read_text('utf-8'))
                  for i in (1, 2, 3)]
        canary = assess_canary_summary(summary, rounds)
    except (OSError, ValueError, TypeError) as exc:
        return {'status': 'BLOCKED', 'reason': 'CANARY_RECORD_INVALID:' + type(exc).__name__,
                'production_release_authorized': False}
    return {'status': 'P41_V3_P2_ATTESTED_PASS' if canary['status'] == 'V3_P2_CANARY_3_OF_3_PASS'
            else 'BLOCKED', 'canary': canary,
            'note': 'Synthetic live fixture only; not general production reliability',
            'automated_merge_authorized': False, 'production_release_authorized': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('artifacts', 'profile', 'manifest'):
        p.add_argument('--' + n, type=Path, required=True)
    p.add_argument('--run-id', type=int, required=True)
    p.add_argument('--commit', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--key-id', required=True)
    a = p.parse_args(argv)
    secret = os.environ.get('AGENTFORGE_V3_EVIDENCE_KEY', '').encode('utf-8')
    if len(secret) < 32:
        print(json.dumps({'status': 'BLOCKED', 'reason': 'INDEPENDENT_SIGNING_KEY_REQUIRED'}))
        return 2
    got = verify(a.artifacts, a.profile, a.manifest, run_id=a.run_id,
                 commit=a.commit, model=a.model, key_id=a.key_id, secret=secret)
    print(json.dumps(got, ensure_ascii=False, indent=2))
    return 0 if got['status'] == 'P41_V3_P2_ATTESTED_PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
