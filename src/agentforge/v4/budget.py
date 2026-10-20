"""Operator-supplied usage accounting; cannot silently raise an execution budget."""
from __future__ import annotations
from dataclasses import dataclass
from .core import ControlDenied


@dataclass(frozen=True)
class Usage:
    attempts: int
    elapsed_seconds: int
    cost_usd: float


def check_budget(budget: dict, observed: Usage) -> dict:
    if (type(observed.attempts) is not int or observed.attempts < 0 or
        type(observed.elapsed_seconds) is not int or observed.elapsed_seconds < 0 or
        type(observed.cost_usd) not in (int, float) or not 0 <= observed.cost_usd < float('inf')):
        raise ControlDenied('Usage counters invalid')
    allowed = (
        observed.attempts <= budget['max_attempts'] and
        observed.elapsed_seconds <= budget['max_runtime_seconds'] and
        observed.cost_usd <= budget['max_cost_usd']
    )
    return {'status': 'WITHIN_BUDGET' if allowed else 'BUDGET_EXCEEDED_BLOCKED',
            'can_continue': bool(allowed), 'measurement_authenticated': False,
            'note': 'Only trusted executor or provider telemetry can supply authoritative usage'}
