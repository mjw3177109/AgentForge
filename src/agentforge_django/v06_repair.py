"""V0.6: max-one repair, max-five model calls, max-two independent Docker gates.

Trust boundary: models produce typed text; the trusted worker writes candidate
files in disposable copies; only fixed Docker check/test commands execute them.
No generated commands, customer DB access, push, PR or production deployment.
"""
import ast
import difflib
import hashlib
import json
import re
import tempfile
import time
from pathlib import Path

from .guard import BoundaryDenied, validate_write_scopes
from .v05_coding import (
    CodingPlan, CodingProposal, IndependentReview, _call, _safe_python,
)
from .verification import copy_workspace
from .docker_verify import docker_verification


class Budget:
    def __init__(self, max_calls=5, max_validations=2, seconds=570):
        self.max_calls = max_calls
        self.max_validations = max_validations
        self.deadline = time.monotonic() + seconds
        self.calls = 0
        self.validations = 0

    def check_time(self):
        if time.monotonic() >= self.deadline:
            raise BoundaryDenied("V0.6 job budget elapsed")

    def call(self, client, role, instruction, schema):
        self.check_time()
        if self.calls >= self.max_calls:
            raise BoundaryDenied("V0.6 model request budget exhausted")
        self.calls += 1  # Count attempted requests, including failures.
        return _call(client, role, instruction, schema)

    def verify(self, workspace):
        self.check_time()
        if self.validations >= self.max_validations:
            raise BoundaryDenied("V0.6 verification budget exhausted")
        self.validations += 1
        # 2 fixed subprocesses (check/test) with a 90s ceiling each.
        result = docker_verification(workspace, with_tests=True, timeout=90)
        if result.get("backend") != "docker-offline":
            raise BoundaryDenied("Independent Docker backend evidence missing")
        return result

    def snapshot(self):
        return {
            "role_requests": self.calls,
            "docker_verification_rounds": self.validations,
            "max_role_requests": self.max_calls,
            "max_docker_rounds": self.max_validations,
            "billing_cost_known": False,
        }


def _validated_changes(root, plan, proposal, original, ceilings):
    if len(proposal.edits) != len({x.path for x in proposal.edits}):
        raise BoundaryDenied("Duplicate candidate edit")
    changes = {}
    for edit in proposal.edits:
        if edit.path not in plan.files:
            raise BoundaryDenied("Unplanned source file edit")
        _safe_python(root, edit.path, ceilings)
        if edit.content == original[edit.path]:
            raise BoundaryDenied("Unchanged source submitted as a modification")
        try:
            ast.parse(edit.content, filename=edit.path)
        except (SyntaxError, ValueError) as exc:
            raise BoundaryDenied("Invalid Python candidate") from exc
        changes[edit.path] = edit.content
    if not changes:
        raise BoundaryDenied("Empty proposal")
    return changes


def _diff(original, changes):
    patch = "".join(
        "".join(difflib.unified_diff(
            original[path].splitlines(keepends=True),
            changes[path].splitlines(keepends=True),
            fromfile="a/" + path, tofile="b/" + path,
        )) for path in sorted(changes)
    )
    if not patch or len(patch.encode("utf-8")) > 100000:
        raise BoundaryDenied("Patch missing or over 100 KB")
    return patch


def _safe_outcome(result, *, attempt):
    checks = result.get("checks", [])
    counts = []
    for item in checks if isinstance(checks, list) else []:
        if isinstance(item, dict):
            raw = str(item.get("stdout", "")) + "\n" + str(item.get("stderr", ""))
            counts.extend(int(n) for n in re.findall(
                r"\bRan\s+([0-9]+)\s+tests?\b", raw,
            ))
    # Retain only numeric counts, not stdout/stderr or secrets.
    return {
        "attempt": attempt,
        "passed": result.get("passed") is True,
        "backend": result.get("backend"),
        "business_tests_executed": result.get("business_tests_executed") is True,
        "business_test_count": max(counts, default=0),
        "checks": [{
            "success": check.get("success") is True,
            "reason": str(check.get("reason", ""))[:80],
            "returncode": check.get("returncode"),
        } for check in checks if isinstance(check, dict)][:2],
    }


def _accepted(result):
    checks = result.get("checks", [])
    return (
        result.get("backend") == "docker-offline"
        and result.get("passed") is True
        and result.get("business_tests_executed") is True
        and len(checks) == 2
        and all(isinstance(c, dict) and c.get("success") is True for c in checks)
    )


def produce_candidate_v06(client, source_root, request_text, allowed_scopes):
    """One Planner/Executor/Reviewer, then one Fixer/Reviewer only on test failure."""
    if not 1 <= len(request_text.strip()) <= 4000:
        raise BoundaryDenied("Requirement size invalid")
    ceilings = validate_write_scopes(allowed_scopes)
    budget = Budget()
    with tempfile.TemporaryDirectory(prefix="agentforge-v06-") as temp:
        original_root = copy_workspace(source_root, Path(temp) / "source")
        plan = budget.call(client, "Planner", json.dumps({
            "requirement": request_text,
            "scope": ceilings,
            "rules": "Select 1-3 existing .py files. No tests, settings, migrations, "
            "new files, commands, secrets or deployment changes.",
        }, ensure_ascii=False), CodingPlan)
        if len(set(plan.files)) != len(plan.files):
            raise BoundaryDenied("Duplicated planned file")
        original = {
            path: _safe_python(original_root, path, ceilings).read_text("utf-8")
            for path in plan.files
        }
        first = budget.call(client, "Executor", json.dumps({
            "requirement": request_text, "plan": plan.model_dump(),
            "original": original,
            "rules": "Return full replacement content only, no new paths.",
        }, ensure_ascii=False), CodingProposal)
        pending = _validated_changes(original_root, plan, first, original, ceilings)
        events = []
        for attempt in (1, 2):
            patch = _diff(original, pending)
            review = budget.call(client, "Reviewer", json.dumps({
                "requirement": request_text, "plan": plan.model_dump(),
                "diff": patch, "retry": attempt > 1,
                "rules": "Approve only scoped minimal source edits; tests NOT yet run.",
            }, ensure_ascii=False), IndependentReview)
            if review.decision != "APPROVE":
                events.append({"attempt": attempt, "review": review.decision,
                               "verification": "NOT_RUN"})
                return {
                    "status": "BLOCKED", "reason": "REVIEW_NOT_APPROVED",
                    "review_decision": review.decision, "repair_attempts": attempt-1,
                    "rounds": events, "budget": budget.snapshot(),
                    "production_release_authorized": False,
                }
            workspace = copy_workspace(original_root, Path(temp) / ("candidate-" + str(attempt)))
            for rel, content in pending.items():
                _safe_python(workspace, rel, ceilings).write_text(content, "utf-8")
            verification = budget.verify(workspace)
            evidence = _safe_outcome(verification, attempt=attempt)
            events.append({"attempt": attempt, "review": review.decision,
                           "verification": evidence})
            if _accepted(verification):
                return {
                    "status": "PROPOSED", "reason": "DOCKER_VERIFIED_CANDIDATE",
                    "review_decision": review.decision,
                    "repair_attempts": attempt-1,
                    "rounds": events, "budget": budget.snapshot(),
                    "model_calls": budget.calls,
                    "source_files": sorted(pending),
                    "candidate_patch": patch,
                    "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                    "independent_verification": evidence,
                    "production_release_authorized": False,
                }
            if attempt == 2:
                break
            # Fail closed on missing tests, Docker gate exceptions or infrastructure
            # failures; only actual failing Django checks can trigger repair.
            checks = verification.get("checks", [])
            if (
                verification.get("backend") != "docker-offline"
                or not checks
                or any(x.get("reason") in {"DOCKER_TIMEOUT", "DOCKER_LAUNCH_ERROR",
                                          "NO_POSITIVE_DJANGO_TEST_COUNT"}
                       for x in checks)
                or verification.get("passed") is not False
            ):
                break
            next_proposal = budget.call(client, "Fixer", json.dumps({
                "requirement": request_text,
                "plan": plan.model_dump(),
                "original": original,
                "attempted_diff": patch,
                "sanitized_verification": evidence,
                "rules": "One final repair. Reuse ONLY planned existing files. "
                "Do not edit tests, settings or credentials.",
            }, ensure_ascii=False), CodingProposal)
            pending = _validated_changes(original_root, plan, next_proposal, original, ceilings)
            if _diff(original, pending) == patch:
                break
        return {
            "status": "FAILED", "reason": "VERIFICATION_FAILED_OR_REPAIR_EXHAUSTED",
            "review_decision": "APPROVE",
            "repair_attempts": max(0, budget.validations-1),
            "rounds": events, "budget": budget.snapshot(),
            "model_calls": budget.calls, "candidate_patch": None,
            "independent_verification": events[-1].get("verification", {}),
            "production_release_authorized": False,
        }
