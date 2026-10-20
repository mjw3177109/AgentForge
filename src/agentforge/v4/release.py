"""V4 release gates fail closed; no merge or production deployment capability."""
from __future__ import annotations
from typing import Any


def assess_maturity(*, offline_matrix: dict[str, Any], synthetic_live: dict[str, Any] | None,
                    project_behavior: dict[str, Any] | None) -> dict:
    issues = []
    if not isinstance(offline_matrix, dict):
        offline_matrix = {}
    for version in ('3.11', '3.12'):
        entry = offline_matrix.get(version)
        if not isinstance(entry, dict) or entry.get('runs_required') != 3 or entry.get('runs_passed') != 3 or entry.get('status') != 'PASS':
            issues.append(f'PYTHON_{version}_THREE_RUNS_NOT_VERIFIED')
    if not isinstance(synthetic_live, dict) or synthetic_live.get('independent_verified') is not True or synthetic_live.get('status') != 'SYNTHETIC_V3_P2_EVIDENCE_VERIFIED':
        issues.append('REAL_V3_P2_THREE_ROUND_ATTESTATION_MISSING')
    # Synthetic points fixture never proves integrated application correctness.
    if not isinstance(project_behavior, dict) or project_behavior.get('independent_verified') is not True or project_behavior.get('scope') != 'REAL_PROJECT_BEHAVIOR':
        issues.append('REAL_PROJECT_BEHAVIOR_EVIDENCE_MISSING')
    # Caller-supplied booleans cannot authenticate GitHub runs or application E2E.
    return {
        'status': 'V4_ACCEPTANCE_CANDIDATE_NEEDS_HUMAN_REVIEW' if not issues else 'BLOCKED',
        'issues': issues,
        'authenticated_by_this_function': False,
        'production_release_authorized': False,
        'auto_merge_authorized': False,
        'note': 'Maturity check is advisory; independent CI and live attestors must validate source claims',
    }
