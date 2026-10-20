"""No external model, database or GitHub credentials needed."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from agentforge.evidence_v3 import EXPECTED_V20_GATES, attest, collect_v20, verify_v20
from agentforge.evidence_v3.v20 import EvidenceValidationError, SNAPSHOT_FILES

SECRET = b"z" * 48
COMMIT = "f" * 40
MODEL = "deepseek-test"
RUN_ID = 39103687560


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else data,
                    encoding="utf-8")


def _payload():
    return {
        "status": "SUCCESS", "review": {"status": "APPROVE", "evidence": ["TASK-1"]},
        "pr_url": None,
        "task_runs": [
            {"agent": agent, "task_id": f"TASK-{i+1}", "status": "SUCCESS",
             "commit": COMMIT, "message": "done"}
            for i, agent in enumerate(("database", "backend", "miniapp", "admin"))],
    }


def _concurrent():
    return {"seed": {"exit_code": 0},
            "inserts": [{"exit_code": 0}, {"exit_code": 1, "stderr": "ERROR 1062 Duplicate entry"}],
            "count": {"exit_code": 0, "stdout": "1\n"}}


def create_fixture(tmp_path: Path, *, fail_round: int = 0):
    root = tmp_path / "artifacts" / "v20-stability"
    profile = tmp_path / "profiles.yaml"
    _write(profile, "allowed_verification_executables: []\n")
    rounds = []
    for i in (1, 2, 3):
        failed = i == fail_round
        folder = root / f"round_{i:02d}"
        gates = []
        for gate in EXPECTED_V20_GATES:
            gates.append({"name": gate, "status": "PASS", "exit_code": 0})
            if gate == "mysql_concurrent_ledger_uniqueness":
                _write(folder / f"{gate}.log", _concurrent())
            else:
                extra = "points_account\npoints_ledger\n" if gate == "mysql_schema" else ""
                _write(folder / f"{gate}.log", "exit_code=0\n" + extra)
        record = {
            "round": i, "status": "FAIL" if failed else "PASS",
            "stage": "maven" if failed else "passed",
            "reason": "Java compilation error" if failed else "Success",
            "benchmark_exit_code": 2 if failed else 0,
            "initial_agents": ["database", "backend", "miniapp", "admin"],
            "repair_agents": [], "review_status": "APPROVE", "gates": gates,
        }
        for source in SNAPSHOT_FILES:
            _write(folder / "generated-repo" / source, f"fixture round {i} source {source}\n")
        _write(folder / "v20_result.json", record)
        _write(folder / "v20_runner_stdout.txt", _payload())
        _write(folder / "v20_runner_stderr.txt", "")
        rounds.append(record)
    passed = 3 - bool(fail_round)
    _write(root / "summary.json", {
        "overall": "PASS" if passed == 3 else "FAIL",
        "rounds_required": 3, "rounds_passed": passed,
        "all_reviewer_approve": True,
        "results": rounds,
    })
    return root, profile


def collect(root, profile):
    return collect_v20(artifact_dir=root, run_id=RUN_ID, commit_sha=COMMIT,
                       model_id=MODEL, trusted_profile=profile)


def verify(manifest, root, profile, **kwargs):
    params = dict(artifact_dir=root, trusted_profile=profile,
                  expected_run_id=RUN_ID, expected_commit_sha=COMMIT,
                  expected_model_id=MODEL, expected_key_id="trusted-ci",
                  secret=SECRET)
    params.update(kwargs)
    return verify_v20(manifest, **params)


def signed(root, profile):
    return attest(collect(root, profile), secret=SECRET, key_id="trusted-ci")


def test_realistic_happy_path_has_three_rounds_and_ten_gates(tmp_path):
    root, profile = create_fixture(tmp_path)
    candidate = collect(root, profile)
    assert candidate["assessment"]["overall"] == "PASS"
    assert len(candidate["assessment"]["rounds"]) == 3
    assert len(candidate["inputs"]) == 3 * (3 + 10 + len(SNAPSHOT_FILES)) + 1
    assert len(candidate["assessment"]["rounds"][0]["gate_evidence"]) == 10
    assert len(candidate["assessment"]["rounds"][0]["task_evidence"]) == 4
    assert candidate["assessment"]["rounds"][0]["snapshot_sha256"]
    assert verify(signed(root, profile), root, profile)["status"] == "VERIFIED_PASS"


def test_source_log_tampering_is_rejected(tmp_path):
    root, profile = create_fixture(tmp_path)
    manifest = signed(root, profile)
    with (root / "round_02" / "maven.log").open("a", encoding="utf-8") as output:
        output.write("corrupt")
    report = verify(manifest, root, profile)
    assert report["status"] == "BLOCKED"
    assert "EVIDENCE_DRIFT:inputs" in report["issues"]


def test_summary_claim_tampering_is_rejected(tmp_path):
    root, profile = create_fixture(tmp_path)
    manifest = signed(root, profile)
    data = json.loads((root / "summary.json").read_text("utf-8"))
    data["rounds_passed"] = 2
    _write(root / "summary.json", data)
    assert verify(manifest, root, profile)["status"] == "BLOCKED"


def test_unsigned_manifest_is_blocked(tmp_path):
    root, profile = create_fixture(tmp_path)
    assert verify(collect(root, profile), root, profile)["status"] == "BLOCKED"


def test_signed_content_tamper_is_blocked(tmp_path):
    root, profile = create_fixture(tmp_path)
    manifest = signed(root, profile)
    manifest["assessment"]["rounds_passed"] = 2
    assert "SIGNATURE_MISMATCH" in verify(manifest, root, profile)["issues"]


@pytest.mark.parametrize("ref", ["expected_run_id", "expected_commit_sha", "expected_model_id", "expected_key_id"])
def test_external_context_pinning_rejects_replay(tmp_path, ref):
    root, profile = create_fixture(tmp_path)
    manifest = signed(root, profile)
    override = {"expected_run_id": 10, "expected_commit_sha": "a"*40,
                "expected_model_id": "other-model", "expected_key_id": "untrusted"}
    assert verify(manifest, root, profile, **{ref: override[ref]})["status"] == "BLOCKED"


def test_wrong_signer_key_rejected(tmp_path):
    root, profile = create_fixture(tmp_path)
    assert verify(signed(root, profile), root, profile, secret=b"y"*48)["status"] == "BLOCKED"


def test_mixed_round_status_cannot_be_reported_as_pass(tmp_path):
    root, profile = create_fixture(tmp_path, fail_round=1)
    candidate = collect(root, profile)
    assert candidate["assessment"]["overall"] == "FAIL"
    assert candidate["assessment"]["rounds_passed"] == 2
    assert verify(attest(candidate, secret=SECRET, key_id="trusted-ci"), root, profile)["status"] == "BLOCKED"


def test_missing_gate_is_unverified(tmp_path):
    root, profile = create_fixture(tmp_path)
    record = json.loads((root / "round_02" / "v20_result.json").read_text("utf-8"))
    record["gates"].pop()
    _write(root / "round_02" / "v20_result.json", record)
    assert collect(root, profile)["assessment"]["overall"] != "PASS"


def test_duplicate_gate_rejected(tmp_path):
    root, profile = create_fixture(tmp_path)
    record = json.loads((root / "round_03" / "v20_result.json").read_text("utf-8"))
    record["gates"].append(deepcopy(record["gates"][0]))
    _write(root / "round_03" / "v20_result.json", record)
    assert "DUPLICATE_GATE" in collect(root, profile)["assessment"]["rounds"][2]["issues"]


def test_missing_gate_log_must_not_pass(tmp_path):
    root, profile = create_fixture(tmp_path)
    (root / "round_01" / "npm_vite.log").unlink()
    assert collect(root, profile)["assessment"]["overall"] == "UNVERIFIED"


def test_symlinked_gate_log_denied(tmp_path):
    root, profile = create_fixture(tmp_path)
    target = root / "round_01" / "maven.log"
    target.unlink()
    target.symlink_to(root / "round_02" / "maven.log")
    assert collect(root, profile)["assessment"]["overall"] != "PASS"


def test_malicious_mysql_log_cannot_pass(tmp_path):
    root, profile = create_fixture(tmp_path)
    _write(root / "round_03" / "mysql_concurrent_ledger_uniqueness.log",
           {"seed": {"exit_code": 0}, "inserts": [{"exit_code": 0}, {"exit_code": 0}],
            "count": {"exit_code": 0, "stdout": "2"}})
    assert "MYSQL_CONCURRENCY_BEHAVIOR_MISMATCH" in collect(root, profile)["assessment"]["rounds"][2]["issues"]


def test_profile_change_invalidates_manifest(tmp_path):
    root, profile = create_fixture(tmp_path)
    manifest = signed(root, profile)
    profile.write_text("different: true\n", encoding="utf-8")
    assert verify(manifest, root, profile)["status"] == "BLOCKED"


def test_bad_original_summary_fail_closed(tmp_path):
    root, profile = create_fixture(tmp_path)
    summary = json.loads((root / "summary.json").read_text())
    summary["overall"] = "PASS"
    summary["rounds_passed"] = 3
    (root / "round_03" / "v20_result.json").unlink()
    _write(root / "summary.json", summary)
    assert collect(root, profile)["assessment"]["overall"] != "PASS"


def test_evidence_age_rejected(tmp_path):
    root, profile = create_fixture(tmp_path)
    manifest = collect(root, profile)
    manifest["generated_at"] = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    manifest = attest(manifest, secret=SECRET, key_id="trusted-ci")
    assert "STALE_OR_FUTURE_EVIDENCE" in verify(manifest, root, profile)["issues"]


def test_bad_key_rejected(tmp_path):
    root, profile = create_fixture(tmp_path)
    with pytest.raises(EvidenceValidationError):
        attest(collect(root, profile), secret=b"short", key_id="trusted-ci")


def test_invalid_commit_rejected(tmp_path):
    root, profile = create_fixture(tmp_path)
    with pytest.raises(EvidenceValidationError):
        collect_v20(artifact_dir=root, run_id=RUN_ID, commit_sha="fbb4eaba",
                    model_id=MODEL, trusted_profile=profile)


def test_generated_source_tamper_is_rejected(tmp_path):
    root, profile = create_fixture(tmp_path)
    manifest = signed(root, profile)
    source = root / "round_02" / "generated-repo" / SNAPSHOT_FILES[0]
    source.write_text("changed SQL", encoding="utf-8")
    assert "EVIDENCE_DRIFT:inputs" in verify(manifest, root, profile)["issues"]


def test_missing_generated_snapshot_never_passes(tmp_path):
    root, profile = create_fixture(tmp_path)
    (root / "round_02" / "generated-repo" / SNAPSHOT_FILES[0]).unlink()
    assert collect(root, profile)["assessment"]["overall"] == "UNVERIFIED"


def test_cli_collect_verify_and_no_overwrite(tmp_path, monkeypatch, capsys):
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "scripts" / "v3_evidence.py"
    spec = importlib.util.spec_from_file_location("v3_evidence_cli", script)
    assert spec and spec.loader
    import sys
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    root, profile = create_fixture(tmp_path)
    monkeypatch.setenv("AGENTFORGE_V3_EVIDENCE_KEY", "z" * 48)
    output = tmp_path / "envelope.json"
    collect_args = ["collect", "--artifacts", str(root), "--profile", str(profile),
                    "--run-id", str(RUN_ID), "--commit", COMMIT,
                    "--model-id", MODEL, "--key-id", "trusted-ci", "--output", str(output)]
    assert module.main(collect_args) == 0
    assert json.loads(output.read_text())["assessment"]["overall"] == "PASS"
    assert module.main(collect_args) == 2  # exclusive create; first file remains unchanged
    verify_args = ["verify", "--artifacts", str(root), "--profile", str(profile),
                   "--manifest", str(output), "--expected-run-id", str(RUN_ID),
                   "--expected-commit", COMMIT, "--expected-model-id", MODEL,
                   "--expected-key-id", "trusted-ci"]
    assert module.main(verify_args) == 0
    assert "VERIFIED_PASS" in capsys.readouterr().out


def test_cli_refuses_no_key(tmp_path, monkeypatch):
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "scripts" / "v3_evidence.py"
    spec = importlib.util.spec_from_file_location("v3_evidence_cli_no_key", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root, profile = create_fixture(tmp_path)
    monkeypatch.delenv("AGENTFORGE_V3_EVIDENCE_KEY", raising=False)
    assert module.main(["collect", "--artifacts", str(root), "--profile", str(profile),
        "--run-id", str(RUN_ID), "--commit", COMMIT, "--model-id", MODEL,
        "--key-id", "trusted-ci", "--output", str(tmp_path / "envelope.json")]) == 2
    assert not (tmp_path / "envelope.json").exists()
