"""Independent V4.1 envelope: P1 integrity + *executed* P2 + Java service gate.

Trust boundary: caller supplies run/commit/model and two secrets from a separate
verifier job. No signing material belongs in the LLM/Agent execution job.
"""
from __future__ import annotations
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any

from .proof import evaluate_runtime_trace

SCHEMA = "agentforge.v41.live-execution-attestation/1"
DOMAIN = b"agentforge-v41-live-execution-attestation-v1\n"
SHA = re.compile(r"[0-9a-f]{40}\Z")
MODEL_MAX = 200


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def safe_read(root: Path, relative: str) -> bytes:
    if (not relative or relative.startswith("/") or "\\" in relative
            or any(piece in {"", ".", ".."} for piece in relative.split("/"))):
        raise ValueError("UNSAFE_RELATIVE_EVIDENCE_PATH")
    current = root
    for segment in relative.split("/"):
        current = current / segment
        if current.is_symlink():
            raise ValueError("SYMLINKED_EVIDENCE")
    if not current.is_file() or not current.resolve().is_relative_to(root):
        raise ValueError("MISSING_EVIDENCE_FILE:" + relative)
    if current.stat().st_size > 1_000_000:
        raise ValueError("EVIDENCE_FILE_TOO_LARGE")
    return current.read_bytes()


def _load_json(root: Path, relative: str) -> dict:
    obj = json.loads(safe_read(root, relative))
    if not isinstance(obj, dict):
        raise ValueError("EXPECTED_EVIDENCE_OBJECT")
    return obj


def _verified_new_gate(root: Path, round_no: int) -> None:
    prefix = f"round_{round_no:02d}/"
    record = _load_json(root, prefix + "v20_result.json")
    output = _load_json(root, prefix + "v20_runner_stdout.txt")
    trace = _load_json(root, prefix + "p2_runtime_proof.json")
    verified = evaluate_runtime_trace(trace, output)
    if verified["status"] != "PASS" or record.get("v41_p2_executed") != verified:
        raise ValueError(f"ROUND_{round_no}_P2_EXECUTION_PROOF_FAILED")
    svc = record.get("v41_service_gate")
    if (not isinstance(svc, dict) or svc.get("name") != "java_mysql_service_exactly_once"
            or svc.get("status") != "PASS" or svc.get("exit_code") != 0
            or svc.get("trusted_test_executed") is not True):
        raise ValueError(f"ROUND_{round_no}_JAVA_SERVICE_GATE_FAILED")
    log = _load_json(root, prefix + "v41_java_service_gate.log")
    if log.get("result") != svc:
        raise ValueError(f"ROUND_{round_no}_SERVICE_LOG_RECORD_MISMATCH")
    stages = log.get("stages")
    if (not isinstance(stages, list) or [s.get("step") for s in stages if isinstance(s, dict)]
            != ["create", "migrate", "trusted_java_maven", "cleanup"]
            or len(stages) != 4 or any(s.get("returncode") != 0 for s in stages)):
        raise ValueError(f"ROUND_{round_no}_SERVICE_RUN_STAGES_INVALID")
    if record.get("status") != "PASS" or record.get("stage") != "passed":
        raise ValueError(f"ROUND_{round_no}_NOT_PASSED")


def _paths() -> list[str]:
    return [f"round_{n:02d}/{name}" for n in (1, 2, 3)
            for name in ("p2_runtime_proof.json", "v41_java_service_gate.log")]


def _require_claims(root: Path):
    summary = _load_json(root, "summary.json")
    if (summary.get("overall") != "PASS" or summary.get("rounds_required") != 3
            or summary.get("rounds_passed") != 3
            or summary.get("v41_mode") != "P2_EXECUTED_JAVA_EXACTLY_ONCE_GATE"):
        raise ValueError("V41_THREE_OF_THREE_NOT_PASSED")
    rounds = [_load_json(root, f"round_{n:02d}/v20_result.json") for n in (1, 2, 3)]
    if summary.get("results") != rounds or [r.get("round") for r in rounds] != [1, 2, 3]:
        raise ValueError("V41_ROUND_SUMMARY_MISMATCH")
    for n in (1, 2, 3):
        _verified_new_gate(root, n)


def _verify_p1(root: Path, manifest: Path, profile: Path, *, run_id: int,
               commit: str, model: str, secret: bytes) -> None:
    from agentforge.acceptance_v3 import validate_attested_run
    result = validate_attested_run(
        manifest=manifest, artifacts=root, trusted_profile=profile,
        expected_run_id=run_id, expected_commit=commit,
        expected_model=model, expected_key_id="v41-p1-trusted",
        secret=secret,
    )
    if result.get("status") != "INDEPENDENT_LIVE_3_OF_3_VERIFIED":
        raise ValueError("V41_P1_INDEPENDENT_ATTESTATION_FAILED")


def create_attestation(root: Path, p1_manifest: Path, profile: Path, *,
                       run_id: int, commit: str, model: str,
                       p1_key: bytes, v41_key: bytes) -> dict:
    if (type(run_id) is not int or run_id < 1 or not SHA.fullmatch(commit)
            or not isinstance(model, str) or not (1 <= len(model) <= MODEL_MAX)
            or len(p1_key) < 32 or len(v41_key) < 32):
        raise ValueError("INVALID_PINNED_CLAIMS_OR_SIGNING_KEYS")
    if root.is_symlink():
        raise ValueError("SYMLINKED_ARTIFACT_ROOT")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("UNSAFE_ARTIFACT_ROOT")
    if p1_manifest.is_symlink() or not p1_manifest.is_file():
        raise ValueError("UNTRUSTED_P1_MANIFEST")
    _verify_p1(root, p1_manifest, profile, run_id=run_id, commit=commit,
               model=model, secret=p1_key)
    _require_claims(root)
    files = []
    for relative in _paths():
        data = safe_read(root, relative)
        files.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
                      "size_bytes": len(data)})
    contents = {
        "schema": SCHEMA,
        "run_id": run_id, "commit": commit, "model": model,
        "p1_envelope_sha256": hashlib.sha256(p1_manifest.read_bytes()).hexdigest(),
        "files": files,
        "release_authorized": False,
    }
    mac = hmac.new(v41_key, DOMAIN + canonical(contents), hashlib.sha256).hexdigest()
    return {**contents, "hmac_sha256": mac}


def verify_attestation(envelope: Any, root: Path, p1_manifest: Path, profile: Path, *,
                       run_id: int, commit: str, model: str,
                       p1_key: bytes, v41_key: bytes) -> dict:
    blocked = {"status": "BLOCKED", "independent_verified": False,
               "production_release_authorized": False, "auto_merge_authorized": False}
    try:
        if not isinstance(envelope, dict) or envelope.get("schema") != SCHEMA:
            raise ValueError("V41_ENVELOPE_SCHEMA_INVALID")
        given = envelope.get("hmac_sha256", "")
        if not isinstance(given, str) or not re.fullmatch(r"[0-9a-f]{64}", given):
            raise ValueError("V41_HMAC_MISSING")
        candidate = create_attestation(root, p1_manifest, profile,
                                       run_id=run_id, commit=commit, model=model,
                                       p1_key=p1_key, v41_key=v41_key)
        if (not hmac.compare_digest(given, candidate["hmac_sha256"])
                or envelope != candidate):
            raise ValueError("V41_SIGNATURE_OR_EVIDENCE_MISMATCH")
        return {**blocked, "status": "V41_SYNTHETIC_INDEPENDENTLY_ATTESTED",
                "independent_verified": True, "run_id": run_id, "commit": commit,
                "note": "Synthetic isolated test only; does not authorize merge or production"}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {**blocked, "reason": str(exc)[:400]}
