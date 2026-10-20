"""AgentForge V4 operator-only CLI. No code-writing or process execution commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from . import (ControlDenied, detect_stacks, evaluate_request,
               issue_approval, verify_approval, append_journal, read_journal,
               verify_p41_evidence, propose_batch)


def _load(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ControlDenied('JSON request path invalid or oversized')
    payload = json.loads(path.read_text('utf-8'))
    if not isinstance(payload, dict):
        raise ControlDenied('JSON must contain an object')
    return payload


def _secret(name: str) -> str:
    value = os.getenv(name, '')
    if len(value) < 32:
        raise ControlDenied('Required signing environment secret missing or too short')
    return value


def _operator_approval_token(raw: str) -> str:
    token = _load(Path(raw))
    if set(token) != {'approval_token'} or not isinstance(token['approval_token'], str):
        raise ControlDenied('Approval token file invalid')
    return token['approval_token']


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='Read-only stack discovery')
    inspect.add_argument('--repo-root', type=Path, required=True)

    def req_args(p):
        p.add_argument('--repo-root', type=Path, required=True)
        p.add_argument('--trusted-profile', required=True)
        p.add_argument('--request', type=Path, required=True)

    batch = sub.add_parser('plan-batch', help='Deterministic multi-agent DAG proposal, no execution')
    batch.add_argument('--repo-root', type=Path, required=True)
    batch.add_argument('--trusted-profile', required=True)
    batch.add_argument('--manifest', type=Path, required=True)

    pre = sub.add_parser('preflight', help='Advisory scope and risk preflight')
    req_args(pre)
    approve = sub.add_parser('approve', help='Explicit manual approval token (never escalates scope)')
    req_args(approve)
    approve.add_argument('--operator', required=True)
    approve.add_argument('--ttl', type=int, default=600)
    approve.add_argument('--confirm', required=True, help='Must equal HUMAN_APPROVES_EXISTING_SCOPE')
    check = sub.add_parser('check-approval', help='Verify exact proposal approval')
    req_args(check)
    check.add_argument('--token-file', type=Path, required=True)

    journal = sub.add_parser('journal', help='Add an operator-controlled audit event')
    journal.add_argument('--file', type=Path, required=True)
    journal.add_argument('--event', choices=['PREPARED', 'BLOCKED', 'CANCELLED', 'VERIFICATION_REJECTED'], required=True)
    journal.add_argument('--run-id', required=True)
    journal.add_argument('--request-hash', required=True)
    journal.add_argument('--approval-token-id')
    record_approval = sub.add_parser('record-approved', help='Validate approval token and record once')
    req_args(record_approval)
    record_approval.add_argument('--file', type=Path, required=True)
    record_approval.add_argument('--token-file', type=Path, required=True)

    check_journal = sub.add_parser('verify-journal', help='Read and authenticate audit chain')
    check_journal.add_argument('--file', type=Path, required=True)

    evidence = sub.add_parser('verify-live-evidence', help='Independent P1+V3 P2 canary verifier')
    evidence.add_argument('--artifacts', type=Path, required=True)
    evidence.add_argument('--manifest', type=Path, required=True)
    evidence.add_argument('--profile', type=Path, required=True)
    evidence.add_argument('--run-id', type=int, required=True)
    evidence.add_argument('--commit', required=True)
    evidence.add_argument('--model', required=True)
    evidence.add_argument('--key-id', required=True)
    evidence.add_argument('--journal-file', type=Path, help='After verified PASS only, record evidence in existing prepared audit run')
    evidence.add_argument('--audit-run-id', help='Operator audit run ID, distinct from GitHub numeric ID')
    evidence.add_argument('--request-hash', help='Preflight request digest bound to audit run')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect':
            result = {'status': 'READ_ONLY_DISCOVERY', 'adapters': [a.to_dict() for a in detect_stacks(args.repo_root)],
                      'executed': False, 'release_authorized': False}
            code = 0
        elif args.command == 'plan-batch':
            result = propose_batch(args.repo_root, args.trusted_profile, _load(args.manifest))
            code = 2 if result['status'] == 'BLOCKED' else 0
        elif args.command in ('preflight', 'approve', 'check-approval', 'record-approved'):
            request = _load(args.request)
            admission = evaluate_request(args.repo_root, args.trusted_profile, request)
            if args.command == 'preflight':
                result = admission.to_dict()
                code = 2 if admission.decision == 'BLOCKED' else 0
            elif args.command == 'approve':
                if args.confirm != 'HUMAN_APPROVES_EXISTING_SCOPE':
                    raise ControlDenied('Explicit operator confirmation required')
                token = issue_approval(admission, request, operator=args.operator,
                                       secret=_secret('AGENTFORGE_V4_APPROVAL_KEY'), ttl_seconds=args.ttl)
                # Write raw token only to stdout upon explicit operator request.
                result = {'approval_token': token, 'notice': 'Secret-bearing; store securely, never commit'}
                code = 0
            else:
                token = _operator_approval_token(str(args.token_file))
                result = verify_approval(token, admission, request,
                                         secret=_secret('AGENTFORGE_V4_APPROVAL_KEY'))
                if args.command == 'record-approved':
                    receipt = append_journal(args.file, _secret('AGENTFORGE_V4_AUDIT_KEY'),
                                            run_id=request['run_id'], event='APPROVED',
                                            request_hash=admission.request_hash,
                                            approval_token_id=result['token_id'])
                    result = {**result, 'journal': receipt}
                code = 0
        elif args.command == 'journal':
            result = append_journal(args.file, _secret('AGENTFORGE_V4_AUDIT_KEY'),
                                    run_id=args.run_id, event=args.event,
                                    request_hash=args.request_hash,
                                    approval_token_id=args.approval_token_id)
            code = 0
        elif args.command == 'verify-journal':
            records = read_journal(args.file, _secret('AGENTFORGE_V4_AUDIT_KEY'))
            result = {'status': 'AUTHENTICATED', 'count': len(records),
                      'last_hash': records[-1]['hash'] if records else None,
                      'production_release_authorized': False}
            code = 0
        elif args.command == 'verify-live-evidence':
            result = verify_p41_evidence(
                artifact_dir=args.artifacts, manifest=args.manifest, profile=args.profile,
                run_id=args.run_id, commit_sha=args.commit, model_id=args.model,
                key_id=args.key_id, secret=_secret('AGENTFORGE_V3_EVIDENCE_KEY').encode('utf-8'))
            if result['independent_verified'] and args.journal_file:
                if not args.audit_run_id or not args.request_hash:
                    raise ControlDenied('Journal attestation requires explicit audit run and request hash')
                receipt = append_journal(args.journal_file, _secret('AGENTFORGE_V4_AUDIT_KEY'),
                                         run_id=args.audit_run_id, event='VERIFICATION_ATTESTED',
                                         request_hash=args.request_hash, evidence_hash=result['evidence_hash'])
                result['journal'] = receipt
            code = 0 if result['independent_verified'] else 2
        else:
            raise ControlDenied('Unknown operation')
    except (ControlDenied, OSError, ValueError, KeyError, TypeError) as exc:
        result = {'status': 'BLOCKED', 'reason': type(exc).__name__ + ': ' + str(exc),
                  'production_release_authorized': False}
        code = 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
