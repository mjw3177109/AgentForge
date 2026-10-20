"""Human approval tokens bind one V4 request, scope hash and exact Git SHA.

Token creation requires an out-of-band signer key and explicit operator consent.
No token may grant a scope that the V2 execution profile did not grant.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from typing import Any

from .core import Admission, ControlDenied, canonical, sha256

TOKEN_TYPE = 'agentforge.v4.human-approval/1'


def _key(value: str) -> bytes:
    if not isinstance(value, str) or len(value) < 32 or len(value) > 4096:
        raise ControlDenied('Approval signing key must be a >=32-character secret')
    return value.encode('utf-8')


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _unb64(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9_-]{1,4096}', value):
        raise ControlDenied('Malformed approval token')
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def issue_approval(admission: Admission, request: dict[str, Any], *, operator: str,
                   secret: str, ttl_seconds: int = 900, now: int | None = None) -> str:
    """Only AWAITING_HUMAN_APPROVAL is eligible; never implicit signing."""
    if admission.decision != 'AWAITING_HUMAN_APPROVAL' or admission.request_hash != sha256(request):
        raise ControlDenied('Approval requires exact high-risk in-scope prepared request')
    if not isinstance(operator, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{3,80}', operator):
        raise ControlDenied('Invalid operator')
    if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 1800:
        raise ControlDenied('Approval expiry must be 60..1800 seconds')
    issued = _now() if now is None else now
    if type(issued) is not int or issued <= 0:
        raise ControlDenied('Invalid timestamp')
    payload = {
        'type': TOKEN_TYPE,
        'purpose': 'PROCEED_WITHIN_EXISTING_SCOPE_ONLY',
        'request_hash': admission.request_hash,
        'profile_hash': admission.profile_hash,
        'commit': request['commit'],
        'run_id': request['run_id'],
        'task_id': request['task_id'],
        'operator': operator,
        'issued_at': issued,
        'expires_at': issued + ttl_seconds,
    }
    body = _b64(canonical(payload))
    signature = _b64(hmac.new(_key(secret), body.encode('ascii'), hashlib.sha256).digest())
    return f'{body}.{signature}'


def verify_approval(token: str, admission: Admission, request: dict[str, Any], *,
                    secret: str, now: int | None = None) -> dict[str, Any]:
    if admission.decision != 'AWAITING_HUMAN_APPROVAL' or admission.request_hash != sha256(request):
        raise ControlDenied('Request is no longer the approved high-risk proposal')
    if not isinstance(token, str) or token.count('.') != 1:
        raise ControlDenied('Malformed approval token')
    body, sig = token.split('.')
    expected = _b64(hmac.new(_key(secret), body.encode('ascii'), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ControlDenied('Approval signature invalid')
    try:
        raw = _unb64(body)
        payload = json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ControlDenied('Approval payload invalid') from exc
    if not isinstance(payload, dict) or canonical(payload) != raw:
        raise ControlDenied('Approval payload is not canonical')
    must = {
        'type': TOKEN_TYPE,
        'purpose': 'PROCEED_WITHIN_EXISTING_SCOPE_ONLY',
        'request_hash': admission.request_hash,
        'profile_hash': admission.profile_hash,
        'commit': request['commit'],
        'run_id': request['run_id'],
        'task_id': request['task_id'],
    }
    if any(payload.get(key) != value for key, value in must.items()):
        raise ControlDenied('Cross-run, cross-commit or scope-changed approval denied')
    if set(payload) != set(must) | {'operator', 'issued_at', 'expires_at'}:
        raise ControlDenied('Unexpected approval capability')
    if not isinstance(payload['operator'], str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{3,80}', payload['operator']):
        raise ControlDenied('Invalid operator')
    issued, expires = payload['issued_at'], payload['expires_at']
    current = _now() if now is None else now
    if (any(type(x) is not int for x in (issued, expires, current)) or
        issued > current + 30 or expires <= current or expires <= issued or expires - issued > 1800):
        raise ControlDenied('Approval expired, premature or duration invalid')
    return {'authorized': True, 'operator': payload['operator'],
            'token_id': hashlib.sha256(token.encode()).hexdigest(),
            'scope_extended': False, 'permissions': 'PREEXISTING_SCOPE_ONLY'}
