"""Append-only hash-linked audit journal (tamper-evident, not tamper-proof)."""

import hashlib
import json

from django.db import transaction

from .models import AgentJob, AuditEvent


def record(job, phase, decision, detail=None):
    if detail is None:
        detail = {}
    with transaction.atomic():
        locked = AgentJob.objects.select_for_update().get(pk=job.pk)
        last = AuditEvent.objects.filter(job=locked).order_by("-sequence").first()
        previous_hash = last.event_hash if last else ""
        sequence = last.sequence + 1 if last else 1
        payload = {
            "job": str(locked.pk), "sequence": sequence, "phase": phase,
            "decision": decision, "detail": detail, "previous_hash": previous_hash,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()
        return AuditEvent.objects.create(
            job=locked, sequence=sequence, phase=phase, decision=decision,
            detail=detail, previous_hash=previous_hash, event_hash=digest,
        )


def verify_chain(job):
    previous = ""
    expected_seq = 1
    for event in AuditEvent.objects.filter(job=job).order_by("sequence"):
        if event.sequence != expected_seq or event.previous_hash != previous:
            return False
        payload = {
            "job": str(job.pk), "sequence": event.sequence, "phase": event.phase,
            "decision": event.decision, "detail": event.detail,
            "previous_hash": event.previous_hash,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()
        if digest != event.event_hash:
            return False
        previous = digest
        expected_seq += 1
    return True
