"""Fail-closed, signed evidence envelope for existing V2.0 runner outputs.

This module DOES NOT execute benchmarks, approve PRs, or decide production safety.
A valid HMAC proves integrity under the given key, not the truth of a malicious
runner's claims. Sign only from an independently trusted verification context.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "agentforge.v3.evidence.v20/1"
SIGNATURE_DOMAIN = b"agentforge-v3-evidence-v20-1\n"
EXPECTED_V20_GATES = (
    "node_database-contract_test", "node_backend-contract_test",
    "node_points_test", "node_points-ledger-contract_test", "maven",
    "npm_install", "npm_vite", "mysql_create", "mysql_schema",
    "mysql_concurrent_ledger_uniqueness",
)
AGENTS = ("database", "backend", "miniapp", "admin")
# Stable sources checked by the V2.0 hardened fixture. These are hashed to
# prevent a log from being reused for a different artifact snapshot. Runtime
# node_modules, dist, and Maven output are deliberately excluded.
SNAPSHOT_FILES = (
    "database/migrations/V980100__points.sql",
    "server/pom.xml", "server/src/main/java/com/agentforge/shop/points/PointsService.java",
    "server/src/main/java/com/agentforge/shop/points/PointsController.java",
    "server/src/test/java/com/agentforge/shop/points/VerifiedPointsContractTest.java",
    "verification/backend-contract.test.js", "verification/database-contract.test.js",
    "miniapp/src/api/points.js", "miniapp/tests/points.test.js",
    "admin-web/package.json", "admin-web/src/PointsLedgerView.vue",
    "admin-web/tests/points-ledger-contract.test.js",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_INPUT_BYTES = 16 * 1024 * 1024


class EvidenceValidationError(ValueError):
    """Untrusted/missing evidence; never automatically interpreted as PASS."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_file(root: Path, rel: str) -> Path:
    """Reject traversal, non-canonical filenames, and symlinks in any component."""
    if (not isinstance(rel, str) or not rel or "\\" in rel
            or rel.startswith("/") or any(x in ("", ".", "..") for x in rel.split("/"))):
        raise EvidenceValidationError(f"Noncanonical evidence path: {rel!r}")
    target = root
    for component in rel.split("/"):
        target = target / component
        if target.is_symlink():
            raise EvidenceValidationError(f"Symlink evidence path denied: {rel}")
    if not target.is_file() or not target.resolve().is_relative_to(root):
        raise EvidenceValidationError(f"Missing or out-of-root evidence: {rel}")
    if target.stat().st_size > MAX_INPUT_BYTES:
        raise EvidenceValidationError(f"Evidence too large: {rel}")
    return target


def _read_json(root: Path, rel: str) -> dict[str, Any]:
    path = _safe_file(root, rel)
    try:
        value = json.loads(path.read_text("utf-8"))
    except (UnicodeError, json.JSONDecodeError, OSError) as exc:
        raise EvidenceValidationError(f"Invalid JSON evidence {rel}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"Evidence must be JSON object: {rel}")
    return value


def _digest(root: Path, rel: str) -> dict[str, Any]:
    path = _safe_file(root, rel)
    digester = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digester.update(chunk)
    return {"path": rel, "sha256": digester.hexdigest(), "size_bytes": path.stat().st_size}


def _check_concurrent_mysql(root: Path, rel: str) -> bool:
    try:
        value = _read_json(root, rel)
        seed, inserts, count = value["seed"], value["inserts"], value["count"]
        if not (isinstance(seed, dict) and seed.get("exit_code") == 0
                and isinstance(inserts, list) and len(inserts) == 2 and isinstance(count, dict)):
            return False
        if not all(isinstance(item, dict) for item in inserts):
            return False
        ok = [item for item in inserts if item.get("exit_code") == 0]
        rejected = [item for item in inserts if item.get("exit_code") != 0]
        return (len(ok) == len(rejected) == 1
                and ("Duplicate entry" in str(rejected[0].get("stderr", ""))
                     or "1062" in str(rejected[0].get("stderr", "")))
                and count.get("exit_code") == 0 and str(count.get("stdout", "")).strip() == "1")
    except (EvidenceValidationError, KeyError, TypeError):
        return False


def _check_protocol(stdout: dict[str, Any]) -> bool:
    if (stdout.get("status") != "SUCCESS" or stdout.get("pr_url")
            or not isinstance(stdout.get("review"), dict)
            or stdout["review"].get("status") != "APPROVE"):
        return False
    task_runs = stdout.get("task_runs")
    if not isinstance(task_runs, list):
        return False
    initials, repairs = Counter(), Counter()
    for run in task_runs:
        if not isinstance(run, dict):
            return False
        agent, task_id = run.get("agent"), run.get("task_id")
        if (agent not in AGENTS or not isinstance(task_id, str) or not task_id.startswith("TASK-")
                or run.get("status") != "SUCCESS"
                or not isinstance(run.get("commit"), str)
                or not COMMIT_RE.fullmatch(run["commit"])):
            return False
        if "review repair round" in str(run.get("message", "")):
            repairs[task_id] += 1
        else:
            initials[agent] += 1
    return (all(initials[a] == 1 for a in AGENTS)
            and all(value <= 2 for value in repairs.values()))


def _assess_round(root: Path, i: int, record: dict[str, Any],
                  summary_record: Any, files: list[str], issues: list[str]) -> dict[str, Any]:
    prefix = f"round_{i:02d}/"
    reasons: list[str] = []
    if record != summary_record:
        reasons.append("ROUND_SUMMARY_DISAGREEMENT")
    if record.get("round") != i:
        reasons.append("ROUND_NUMBER_MISMATCH")
    status = record.get("status")
    if status not in {"PASS", "FAIL"}:
        reasons.append("INVALID_ROUND_STATUS")
    if status == "PASS" and (record.get("stage") != "passed"
                             or record.get("review_status") != "APPROVE"
                             or Counter(record.get("initial_agents") or []) != Counter(AGENTS)
                             or record.get("benchmark_exit_code") != 0):
        reasons.append("ROUND_SUCCESS_CLAIM_CONTRADICTION")
    for name in ("v20_result.json", "v20_runner_stdout.txt", "v20_runner_stderr.txt"):
        files.append(prefix + name)
    if status == "PASS":
        # Snapshot signatures include all backend Java sources, not only known
        # fixture filenames, because each autonomous agent can create new classes.
        snapshot_root = root / prefix / "generated-repo"
        if snapshot_root.is_dir() and not snapshot_root.is_symlink():
            discovered = []
            java_root = snapshot_root / "server" / "src"
            if java_root.is_dir() and not java_root.is_symlink():
                for file in java_root.rglob("*.java"):
                    discovered.append(file.relative_to(snapshot_root).as_posix())
            if len(discovered) > 1000:
                reasons.append("TOO_MANY_SNAPSHOT_JAVA_FILES")
            else:
                for relative in sorted(set(discovered) - set(SNAPSHOT_FILES)):
                    name = prefix + "generated-repo/" + relative
                    files.append(name)
                    try:
                        _safe_file(root, name)
                    except EvidenceValidationError:
                        reasons.append("UNSAFE_SNAPSHOT_FILE:" + relative)
        for relative in SNAPSHOT_FILES:
            name = prefix + "generated-repo/" + relative
            files.append(name)
            try:
                _safe_file(root, name)
            except EvidenceValidationError:
                reasons.append("MISSING_SNAPSHOT_FILE:" + relative)
    stdout = None
    try:
        stdout = _read_json(root, prefix + "v20_runner_stdout.txt")
    except EvidenceValidationError:
        if status == "PASS":
            reasons.append("MISSING_OR_INVALID_PROTOCOL_OUTPUT")
    if status == "PASS" and (stdout is None or not _check_protocol(stdout)):
        reasons.append("AGENT_OR_REVIEWER_PROTOCOL_INVALID")
    gates = record.get("gates")
    if not isinstance(gates, list):
        gates = []
        reasons.append("INVALID_GATE_LIST")
    ids = [g.get("name") for g in gates if isinstance(g, dict)]
    if len(ids) != len(set(ids)):
        reasons.append("DUPLICATE_GATE")
    unknown = sorted(set(ids) - set(EXPECTED_V20_GATES), key=str)
    if unknown:
        reasons.append("UNKNOWN_GATES:" + ",".join(map(str, unknown)))
    missing = sorted(set(EXPECTED_V20_GATES) - set(ids))
    if missing:
        reasons.append(("NOT_EXECUTED_GATES:" if status == "FAIL" else "MISSING_GATES:") + ",".join(missing))
    if status == "PASS" and len(ids) != len(EXPECTED_V20_GATES):
        reasons.append("INCOMPLETE_PASS_GATE_LIST")
    gate_status: dict[str, str] = {}
    for g in gates:
        if not isinstance(g, dict) or not isinstance(g.get("name"), str):
            reasons.append("MALFORMED_GATE_RECORD")
            continue
        name = g["name"]
        if name not in EXPECTED_V20_GATES:
            continue
        result = g.get("status")
        gate_status[name] = str(result)
        if result not in {"PASS", "FAIL"}:
            reasons.append(f"INVALID_GATE_STATUS:{name}")
        if type(g.get("exit_code")) is not int or (result == "PASS") != (g.get("exit_code") == 0):
            reasons.append(f"GATE_STATUS_EXIT_MISMATCH:{name}")
        if result != "PASS" and status == "PASS":
            reasons.append(f"ROUND_PASS_WITH_FAILED_GATE:{name}")
        log_rel = prefix + name + ".log"
        files.append(log_rel)
        try:
            log = _safe_file(root, log_rel)
            if name == "mysql_concurrent_ledger_uniqueness":
                if result == "PASS" and not _check_concurrent_mysql(root, log_rel):
                    reasons.append("MYSQL_CONCURRENCY_BEHAVIOR_MISMATCH")
            else:
                first = log.read_text("utf-8", errors="replace").split("\n", 1)[0]
                if first != f"exit_code={g.get('exit_code')}":
                    reasons.append(f"GATE_LOG_EXIT_MISMATCH:{name}")
                if name == "mysql_schema" and result == "PASS":
                    contents = log.read_text("utf-8", errors="replace")
                    if not ("points_account" in contents and "points_ledger" in contents):
                        reasons.append("MYSQL_SCHEMA_CONTENT_MISMATCH")
        except EvidenceValidationError:
            reasons.append(f"MISSING_GATE_LOG:{name}")
    if status == "FAIL":
        reasons.append("RUN_REPORTED_FAILURE:" + str(record.get("stage", "unknown")))
    if reasons:
        issues.extend(f"round_{i:02d}:{reason}" for reason in reasons)
    tasks = []
    if isinstance(stdout, dict) and isinstance(stdout.get("task_runs"), list):
        for run in stdout["task_runs"]:
            if isinstance(run, dict):
                tasks.append({"task_id": run.get("task_id"), "agent": run.get("agent"),
                              "status": run.get("status"), "task_commit_sha": run.get("commit")})
    return {"round": i, "reported_status": status, "task_evidence": tasks,
            "gate_status": gate_status, "missing_gates": missing,
            "assessment": "PASS" if not reasons and status == "PASS" else (
                "FAIL" if status == "FAIL" else
                "UNVERIFIED" if any(s.startswith(("MISSING_", "INCOMPLETE_")) for s in reasons)
                else "FAIL"), "issues": reasons}


def collect_v20(*, artifact_dir: Path, run_id: int, commit_sha: str,
                model_id: str, trusted_profile: Path, validator_version: str = "v3-p1.0") -> dict[str, Any]:
    """Recompute an unsigned candidate envelope from immutable V2 output files.

    Values in ``claims`` are caller assertions until externally pinned/attested.
    Missing or inconsistent data never returns an assessment of PASS.
    """
    if type(run_id) is not int or run_id <= 0:
        raise EvidenceValidationError("GitHub Actions run ID must be positive integer")
    if not isinstance(commit_sha, str) or not COMMIT_RE.fullmatch(commit_sha):
        raise EvidenceValidationError("Full 40-character lowercase commit SHA required")
    if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 200:
        raise EvidenceValidationError("Explicit model ID required")
    if not isinstance(validator_version, str) or not validator_version or len(validator_version) > 80:
        raise EvidenceValidationError("Validator version required")
    root = Path(artifact_dir).resolve(strict=True)
    if not root.is_dir():
        raise EvidenceValidationError("Artifact root must be a directory")
    original_profile = Path(trusted_profile)
    if original_profile.is_symlink():
        raise EvidenceValidationError("Trusted profile symlink denied")
    profile = original_profile.resolve(strict=True)
    if not profile.is_file():
        raise EvidenceValidationError("Trusted profile must be a regular file")
    profile_bytes = profile.read_bytes()
    if len(profile_bytes) > MAX_INPUT_BYTES:
        raise EvidenceValidationError("Profile too large")
    summary = _read_json(root, "summary.json")
    issues: list[str] = []
    if summary.get("rounds_required") != 3:
        issues.append("ROUNDS_REQUIRED_MUST_BE_3")
    results = summary.get("results")
    if not isinstance(results, list) or len(results) != 3:
        issues.append("SUMMARY_MUST_CONTAIN_3_RESULTS")
        results = []
    files: list[str] = ["summary.json"]
    rounds: list[dict[str, Any]] = []
    for i in (1, 2, 3):
        rel = f"round_{i:02d}/v20_result.json"
        try:
            round_record = _read_json(root, rel)
        except EvidenceValidationError as exc:
            issues.append(f"round_{i:02d}:MISSING_OR_INVALID_ROUND:{exc}")
            files.append(rel)
            rounds.append({"round": i, "reported_status": "UNKNOWN",
                           "gate_status": {}, "missing_gates": list(EXPECTED_V20_GATES),
                           "assessment": "UNVERIFIED", "issues": ["MISSING_OR_INVALID_ROUND"]})
            continue
        rounds.append(_assess_round(root, i, round_record,
                     results[i - 1] if len(results) >= i else None, files, issues))
    actual_passed = sum(x["assessment"] == "PASS" for x in rounds)
    claimed_passed = summary.get("rounds_passed")
    if claimed_passed != actual_passed:
        issues.append("ROUNDS_PASSED_SUMMARY_DISAGREEMENT")
    expected_overall = "PASS" if actual_passed == 3 and not issues else "FAIL"
    if summary.get("overall") != expected_overall:
        issues.append("OVERALL_SUMMARY_DISAGREEMENT")
    if summary.get("all_reviewer_approve") != all(
        r.get("reported_status") == "PASS" for r in rounds
    ) and actual_passed == 3:
        issues.append("REVIEWER_SUMMARY_DISAGREEMENT")
    digests = []
    for rel in sorted(set(files)):
        try:
            digests.append(_digest(root, rel))
        except EvidenceValidationError as exc:
            if not any(rel in existing for existing in issues):
                issues.append(f"MISSING_INPUT:{rel}:{exc}")
    digest_by_path = {item["path"]: item["sha256"] for item in digests}
    for round_record in rounds:
        index = round_record["round"]
        round_record["gate_evidence"] = [
            {"gate_id": gate_id, "result": result,
             "artifact_sha256": digest_by_path.get(f"round_{index:02d}/{gate_id}.log")}
            for gate_id, result in sorted(round_record["gate_status"].items())
        ]
        prefix = f"round_{index:02d}/generated-repo/"
        snapshot_hashes = {key[len(prefix):]: value for key, value in digest_by_path.items()
                           if key.startswith(prefix)}
        round_record["snapshot_sha256"] = (_sha256(canonical_json(snapshot_hashes))
            if all(name in snapshot_hashes for name in SNAPSHOT_FILES) else None)
    final = "PASS" if actual_passed == 3 and not issues else (
        "FAIL" if any(r["reported_status"] == "FAIL" for r in rounds) else
        "UNVERIFIED" if any(item.startswith("MISSING_") or ":MISSING_" in item for item in issues)
        else "FAIL")
    return {
        "schema": SCHEMA,
        "origin": "V2_ARTIFACT_IMPORT_NOT_A_RERUN",
        "claims": {"run_id": run_id, "commit_sha": commit_sha, "model_id": model_id,
                   "trusted_profile_sha256": _sha256(profile_bytes),
                   "validator_version": validator_version},
        "assessment": {"overall": final, "rounds_passed": actual_passed,
                       "rounds_required": 3, "rounds": rounds, "issues": issues},
        "inputs": digests,
        "generated_at": _utcnow(),
    }


def _payload(envelope: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in envelope.items() if k != "attestation"}


def attest(envelope: dict[str, Any], *, secret: bytes, key_id: str) -> dict[str, Any]:
    """HMAC sign a candidate from a TRUSTED verifier, not a generated-code runner."""
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise EvidenceValidationError("Evidence signing key needs >=32 bytes of secret entropy")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", key_id):
        raise EvidenceValidationError("Invalid signing key identifier")
    unsigned = _payload(envelope)
    mac = hmac.new(secret, SIGNATURE_DOMAIN + canonical_json(unsigned), hashlib.sha256)
    return {**unsigned, "attestation": {
        "algorithm": "HMAC-SHA256", "key_id": key_id,
        "signature": mac.hexdigest()}}


def verify_v20(envelope: dict[str, Any], *, artifact_dir: Path, trusted_profile: Path,
               expected_run_id: int, expected_commit_sha: str, expected_model_id: str,
               secret: bytes, expected_key_id: str, max_age_hours: float = 168.0) -> dict[str, Any]:
    """Authenticate evidence, rehash every source and re-derive the verdict.

    All expected IDs and the verification key must come from an independent trusted
    context (not fields inside the manifest being verified).
    """
    failure: list[str] = []
    if not isinstance(envelope, dict) or envelope.get("schema") != SCHEMA:
        return {"status": "BLOCKED", "issues": ["UNSUPPORTED_EVIDENCE_SCHEMA"]}
    attestation = envelope.get("attestation")
    if not isinstance(attestation, dict) or attestation.get("algorithm") != "HMAC-SHA256":
        return {"status": "BLOCKED", "issues": ["MISSING_OR_UNSUPPORTED_SIGNATURE"]}
    if attestation.get("key_id") != expected_key_id:
        failure.append("UNEXPECTED_SIGNING_KEY")
    if not isinstance(secret, bytes) or len(secret) < 32:
        return {"status": "BLOCKED", "issues": ["NO_TRUSTED_VERIFICATION_KEY"]}
    sig = attestation.get("signature")
    if not isinstance(sig, str) or not SHA256_RE.fullmatch(sig):
        failure.append("INVALID_SIGNATURE_FORMAT")
    else:
        valid = hmac.new(secret, SIGNATURE_DOMAIN + canonical_json(_payload(envelope)),
                         hashlib.sha256).hexdigest()
        if not hmac.compare_digest(valid, sig):
            failure.append("SIGNATURE_MISMATCH")
    claims = envelope.get("claims")
    if not isinstance(claims, dict):
        return {"status": "BLOCKED", "issues": failure + ["MISSING_CLAIMS"]}
    if claims.get("run_id") != expected_run_id:
        failure.append("RUN_ID_MISMATCH")
    if claims.get("commit_sha") != expected_commit_sha:
        failure.append("COMMIT_SHA_MISMATCH")
    if claims.get("model_id") != expected_model_id:
        failure.append("MODEL_ID_MISMATCH")
    try:
        now = datetime.now(timezone.utc)
        signed_at = datetime.fromisoformat(envelope["generated_at"])
        if signed_at.tzinfo is None:
            raise ValueError("No timezone in signature")
        age = (now - signed_at.astimezone(timezone.utc)).total_seconds()
        if not isinstance(max_age_hours, (int, float)) or not 0 < max_age_hours <= 24 * 365:
            raise ValueError("Invalid max_age_hours")
        if age < -300 or age > max_age_hours * 3600:
            failure.append("STALE_OR_FUTURE_EVIDENCE")
    except (ValueError, KeyError, TypeError, OverflowError):
        failure.append("INVALID_EVIDENCE_TIMESTAMP")
    # Reject unauthenticated inputs before any PASS decision.
    if failure:
        return {"status": "BLOCKED", "issues": failure}
    try:
        current = collect_v20(
            artifact_dir=artifact_dir, run_id=expected_run_id,
            commit_sha=expected_commit_sha, model_id=expected_model_id,
            trusted_profile=trusted_profile,
            validator_version=claims.get("validator_version", ""),
        )
    except (EvidenceValidationError, OSError, TypeError) as exc:
        return {"status": "BLOCKED", "issues": ["INPUT_UNAVAILABLE:" + str(exc)]}
    # Timestamp is the one field intentionally not regenerated identically.
    for key in ("origin", "claims", "assessment", "inputs", "schema"):
        if current[key] != envelope.get(key):
            failure.append("EVIDENCE_DRIFT:" + key)
    return {"status": "VERIFIED_PASS" if not failure and current["assessment"]["overall"] == "PASS"
            else "BLOCKED", "issues": failure + current["assessment"]["issues"],
            "assessment": current["assessment"],
            "note": "Integrity/authenticity of enumerated V2 artifacts only; NOT proof of production safety"}
