"""Append-only, HMAC-authenticated local audit chain.

Recording a claimed verification PASS is disallowed: the only acceptable
verifier outcome is a separate P1-compatible verified evidence receipt.
This is an advisory audit log, not external anchoring or immutable storage.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any

from .core import ControlDenied, canonical

EVENTS = {'PREPARED', 'APPROVED', 'BLOCKED', 'CANCELLED', 'VERIFICATION_ATTESTED', 'VERIFICATION_REJECTED'}
NEXT = {
    None: {'PREPARED'},
    'PREPARED': {'APPROVED', 'BLOCKED', 'CANCELLED', 'VERIFICATION_ATTESTED', 'VERIFICATION_REJECTED'},
    'APPROVED': {'VERIFICATION_ATTESTED', 'VERIFICATION_REJECTED', 'CANCELLED', 'BLOCKED'},
    'BLOCKED': set(), 'CANCELLED': set(),
    'VERIFICATION_ATTESTED': set(), 'VERIFICATION_REJECTED': set(),
}
SAFE_ID = re.compile(r'[A-Za-z0-9_-]{8,100}\Z')


def _key(value: str) -> bytes:
    if not isinstance(value, str) or len(value) < 32:
        raise ControlDenied('Audit key must be >=32 characters')
    return value.encode('utf-8')


def _secure_target(path: Path) -> Path:
    target = path.absolute()
    if not target.parent.is_dir():
        raise ControlDenied('Journal parent directory does not exist')
    for p in (target, *target.parents):
        if p.is_symlink():
            raise ControlDenied('Symlink journal or ancestor denied')
    if target.exists():
        stat_result = target.stat(follow_symlinks=False)
        if not stat.S_ISREG(stat_result.st_mode) or stat_result.st_nlink != 1:
            raise ControlDenied('Journal must be a standalone regular file')
    return target


def _mac(data: dict, secret: bytes) -> str:
    return hmac.new(secret, canonical(data), hashlib.sha256).hexdigest()


def read_journal(path: Path, secret: str) -> list[dict[str, Any]]:
    key = _key(secret)
    target = _secure_target(Path(path))
    if not target.exists():
        return []
    content = target.read_bytes()
    if len(content) > 8 * 1024 * 1024:
        raise ControlDenied('Journal exceeds size limit')
    if content and not content.endswith(b'\n'):
        raise ControlDenied('Journal contains truncated last record')
    result = []
    expected_previous = '0' * 64
    states = {}
    seen_approval_tokens = set()
    for line in content.splitlines():
        if len(line) > 4000:
            raise ControlDenied('Oversized journal record')
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ControlDenied('Corrupt journal JSON') from exc
        if not isinstance(record, dict) or set(record) != {'seq', 'previous_hash', 'payload', 'hash', 'mac'}:
            raise ControlDenied('Invalid audit chain fields')
        unsigned = {k: record[k] for k in ('seq', 'previous_hash', 'payload')}
        if type(record['seq']) is not int or record['seq'] != len(result) + 1 or record['previous_hash'] != expected_previous:
            raise ControlDenied('Broken journal sequence/hash chain')
        digest = hashlib.sha256(canonical(unsigned)).hexdigest()
        if record['hash'] != digest or not hmac.compare_digest(record['mac'], _mac({'hash': digest}, key)):
            raise ControlDenied('Journal tampered / incorrect key')
        event = record['payload']
        if not isinstance(event, dict) or set(event) != {'run_id', 'event', 'request_hash', 'evidence_hash', 'approval_token_id'}:
            raise ControlDenied('Malformed journal event')
        rid = event['run_id']
        if not isinstance(rid, str) or not SAFE_ID.fullmatch(rid) or event['event'] not in EVENTS:
            raise ControlDenied('Invalid journal run/event')
        if event['event'] not in NEXT[states.get(rid)]:
            raise ControlDenied('Illegal audit state transition')
        for field in ('request_hash', 'evidence_hash', 'approval_token_id'):
            v = event[field]
            if v is not None and (not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v)):
                raise ControlDenied('Journal accepts hashes, never raw logs/tokens')
        if event['event'] == 'APPROVED':
            token_id = event['approval_token_id']
            if token_id is None or token_id in seen_approval_tokens:
                raise ControlDenied('Approval token missing or replayed')
            seen_approval_tokens.add(token_id)
        if event['event'] == 'VERIFICATION_ATTESTED' and not event['evidence_hash']:
            raise ControlDenied('Verification PASS requires independently bound evidence hash')
        states[rid] = event['event']
        expected_previous = digest
        result.append(record)
    return result


def append_journal(path: Path, secret: str, *, run_id: str, event: str,
                   request_hash: str, evidence_hash: str | None = None,
                   approval_token_id: str | None = None) -> dict:
    """Single-process-compatible append. Exclusive lockfile fails closed on contention.

    Assumption: journal directory is controlled by operator; no hostile process
    with same permissions as the signer may rewrite the entire file.
    """
    target = _secure_target(Path(path))
    key = _key(secret)
    lock = target.with_name(target.name + '.lock')
    if lock.is_symlink():
        raise ControlDenied('Lock symlink denied')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError as exc:
        raise ControlDenied('Journal busy; stale lock requires operator review') from exc
    try:
        os.close(fd)
        records = read_journal(target, secret)
        states = {rec['payload']['run_id']: rec['payload']['event'] for rec in records}
        if event not in EVENTS or event not in NEXT[states.get(run_id)]:
            raise ControlDenied('Illegal audit transition')
        if not isinstance(run_id, str) or not SAFE_ID.fullmatch(run_id):
            raise ControlDenied('Invalid run id')
        if not isinstance(request_hash, str) or not re.fullmatch('[0-9a-f]{64}', request_hash):
            raise ControlDenied('Invalid request hash')
        previous = [rec['payload'] for rec in records if rec['payload']['run_id'] == run_id]
        if previous and request_hash != previous[0]['request_hash']:
            raise ControlDenied('Run request hash may not change')
        payload = {'run_id': run_id, 'event': event,
                   'request_hash': request_hash, 'evidence_hash': evidence_hash,
                   'approval_token_id': approval_token_id}
        if event == 'APPROVED' and (approval_token_id is None or
            any(r['payload']['approval_token_id'] == approval_token_id for r in records)):
            raise ControlDenied('Missing or already used approval')
        if event == 'VERIFICATION_ATTESTED' and evidence_hash is None:
            raise ControlDenied('Verification receipt missing')
        unsigned = {'seq': len(records) + 1,
                    'previous_hash': records[-1]['hash'] if records else '0' * 64,
                    'payload': payload}
        record_hash = hashlib.sha256(canonical(unsigned)).hexdigest()
        record = {**unsigned, 'hash': record_hash,
                  'mac': _mac({'hash': record_hash}, key)}
        # Revalidate all added values before writing. No freeform reason strings.
        for field in ('evidence_hash', 'approval_token_id'):
            value = payload[field]
            if value is not None and (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)):
                raise ControlDenied('Only digest identifiers are recordable')
        line = canonical(record) + b'\n'
        flags = os.O_APPEND | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
        if not target.exists():
            flags |= os.O_CREAT | os.O_EXCL
        fd = os.open(target, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                raise ControlDenied('Journal replaced while locked')
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        return {'seq': record['seq'], 'event': event, 'chain_hash': record_hash}
    finally:
        lock.unlink(missing_ok=True)
