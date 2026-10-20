"""V3 P4: offline integration checks and fail-closed evidence review.

This module never modifies the worktree, starts an LLM, publishes/merges PRs,
changes an Agent's scope, or authorizes deployment. In particular a self-reported
PASS or a signed historical failure cannot become a release approval.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from agentforge.evidence_v3 import EXPECTED_V20_GATES, verify_v20

COMPONENT_FILES = (
    "src/agentforge/governance/preflight.py",
    "src/agentforge/evidence_v3/v20.py",
    "src/agentforge/repair_v3.py",
    "src/agentforge/memory_v3.py",
    "src/agentforge/acceptance_v3.py",
    "scripts/v3_preflight.py",
    "scripts/v3_evidence.py",
    "scripts/v3_p2_diagnose.py",
    "scripts/v3_p2_integrate.py",
    "scripts/v3_memory.py",
    "scripts/v3_p4_acceptance.py",
    "tests/test_v3_preflight.py",
    "tests/test_v3_evidence.py",
    "tests/test_v3_repair.py",
    "tests/test_v3_p2_installer.py",
    "tests/test_v3_memory.py",
    "tests/test_v3_p4_acceptance.py",
)
LEGACY_FILES = (
    "src/agentforge/policy.py",
    "src/agentforge/autonomous.py",
    "src/agentforge/cli.py",
    "src/agentforge/coding.py",
    "src/agentforge/workspace.py",
    "protocol_bundle/scripts/validate_protocol.py",
    "scripts/run_v20_stability.py",
)
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
MAX_JSON = 16 * 1024 * 1024


class AcceptanceBlocked(ValueError):
    """A prerequisite is missing or untrusted; never interpret as successful."""


def _regular_under_root(root: Path, relative: str) -> Path:
    if (not relative or relative.startswith("/") or "\\" in relative or
            any(x in {"", ".", ".."} for x in relative.split("/"))):
        raise AcceptanceBlocked("NONCANONICAL_INPUT_PATH")
    cursor = root
    for segment in relative.split("/"):
        cursor = cursor / segment
        if cursor.is_symlink():
            raise AcceptanceBlocked("SYMLINK_IN_EVIDENCE_PATH:" + relative)
    if not cursor.is_file() or not cursor.resolve().is_relative_to(root):
        raise AcceptanceBlocked("MISSING_COMPONENT:" + relative)
    return cursor


def inspect_components(repo_root: Path) -> dict[str, Any]:
    """Presence/hash checks only, not a claim of integration correctness."""
    root = Path(repo_root).resolve(strict=True)
    required = COMPONENT_FILES + LEGACY_FILES
    found: dict[str, str] = {}
    issues = []
    for rel in required:
        try:
            found[rel] = hashlib.sha256(_regular_under_root(root, rel).read_bytes()).hexdigest()
        except (AcceptanceBlocked, OSError) as exc:
            issues.append(str(exc))
    return {
        "status": "COMPONENTS_PRESENT_NOT_VERIFIED" if not issues else "BLOCKED",
        "found": found,
        "issues": issues,
        "automated_merge_authorized": False,
        "production_release_authorized": False,
    }


def _json(root: Path, relative: str) -> dict[str, Any]:
    path = _regular_under_root(root, relative)
    if path.stat().st_size > MAX_JSON:
        raise AcceptanceBlocked("OVERSIZED_INPUT:" + relative)
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise AcceptanceBlocked("INVALID_JSON:" + relative) from exc
    if not isinstance(value, dict):
        raise AcceptanceBlocked("NOT_JSON_OBJECT:" + relative)
    return value


def inspect_v20_history(artifact_dir: Path) -> dict[str, Any]:
    """Diagnostic, UNSIGNED summary. Never use this as proof that gates ran."""
    root = Path(artifact_dir).resolve(strict=True)
    try:
        summary = _json(root, "summary.json")
        rounds = []
        for i in (1, 2, 3):
            x = _json(root, f"round_{i:02d}/v20_result.json")
            names = [z.get("name") for z in x.get("gates", []) if isinstance(z, dict)]
            independent_gates_ok = (
                len(names) == len(EXPECTED_V20_GATES) and
                set(names) == set(EXPECTED_V20_GATES) and
                all(z.get("status") == "PASS" and z.get("exit_code") == 0
                    for z in x.get("gates", []) if isinstance(z, dict))
            )
            rounds.append({"round": i, "status": x.get("status"),
                           "reviewer": x.get("review_status"),
                           "independent_gates_reported_pass": independent_gates_ok,
                           "failure_class": x.get("failure_class"),
                           "reason": x.get("reason")})
        matches = (summary.get("results") ==
                   [_json(root, f"round_{i:02d}/v20_result.json") for i in (1, 2, 3)])
        passes = sum(r["status"] == "PASS" and r["reviewer"] == "APPROVE" and
                     r["independent_gates_reported_pass"] for r in rounds)
        claimed = (matches and summary.get("rounds_required") == 3
                   and summary.get("rounds_passed") == passes
                   and summary.get("overall") == ("PASS" if passes == 3 else "FAIL"))
        return {"status": "ELIGIBLE_FOR_INDEPENDENT_P1_VERIFICATION" if passes == 3 and claimed
                else "REPORTED_FAIL" if claimed and passes < 3 else "BLOCKED",
                "rounds": rounds, "reported_rounds_passed": passes,
                "summary_consistent": bool(claimed), "authenticated": False,
                "production_release_authorized": False}
    except (AcceptanceBlocked, OSError) as exc:
        return {"status": "BLOCKED", "issues": [str(exc)],
                "authenticated": False, "production_release_authorized": False}


def validate_attested_run(*, manifest: Path, artifacts: Path,
                          trusted_profile: Path, expected_run_id: int,
                          expected_commit: str, expected_model: str,
                          expected_key_id: str, secret: bytes,
                          max_age_hours: float = 168.0) -> dict[str, Any]:
    """Only P1's independent verification can confirm a real 3/3 live result."""
    if (type(expected_run_id) is not int or expected_run_id <= 0
            or not isinstance(expected_commit, str) or not COMMIT.fullmatch(expected_commit)):
        return {"status": "BLOCKED", "issues": ["INVALID_PINNED_RUN_OR_COMMIT"]}
    try:
        envelope = _json(manifest.parent.resolve(strict=True), manifest.name)
        result = verify_v20(
            envelope, artifact_dir=artifacts, trusted_profile=trusted_profile,
            expected_run_id=expected_run_id, expected_commit_sha=expected_commit,
            expected_model_id=expected_model, expected_key_id=expected_key_id,
            secret=secret, max_age_hours=max_age_hours)
    except (AcceptanceBlocked, OSError, ValueError, TypeError, KeyError) as exc:
        return {"status": "BLOCKED", "issues": [str(exc)]}
    return {"status": "INDEPENDENT_LIVE_3_OF_3_VERIFIED" if result["status"] == "VERIFIED_PASS"
            else "BLOCKED", "p1_status": result["status"],
            "issues": result.get("issues", []),
            "rounds": result.get("assessment", {}).get("rounds", []),
            "automated_merge_authorized": False,
            "production_release_authorized": False,
            "note": "Live V2 benchmark verification only; P0-P3 operational live integration not proven"}


def validate_offline_matrix(reports: dict[str, dict[str, Any]], commit_sha: str) -> dict[str, Any]:
    """Cross-check candidate CI reports; caller MUST independently authenticate CI jobs.

    Unsigned/local inputs NEVER yield a release-ready status, even if both pass.
    """
    issues = []
    for version in ("3.11", "3.12"):
        report = reports.get(version)
        if not isinstance(report, dict):
            issues.append("MISSING_PYTHON_MATRIX:" + version)
            continue
        if (report.get("status") != "OFFLINE_SUITE_PASS" or
                report.get("python_minor") != version or
                report.get("git_commit") != commit_sha or
                report.get("iterations_required") != 3 or
                report.get("iterations_passed") != 3):
            issues.append("UNTRUSTED_OR_FAILED_MATRIX:" + version)
    return {"status": "UNAUTHENTICATED_CANDIDATE" if not issues else "BLOCKED",
            "issues": issues,
            "requires_independent_github_job_verification": True,
            "production_release_authorized": False}


def python_minor() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"
