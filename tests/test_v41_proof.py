"""V4.1 fail-closed proof, no network, no paid models."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import importlib.util
import pytest

from agentforge.v41.proof import evaluate_runtime_trace, verify_trace_file, AGENTS
from agentforge.v41 import attestation
from agentforge.v41.service_gate import check_java_service, _schema_for

ROOT = Path(__file__).resolve().parents[1]

def _protocol():
    return {"status": "SUCCESS", "task_runs": [
        {"task_id": f"TASK-{i:06d}", "agent": agent,
         "status": "SUCCESS", "commit": "a" * 40}
        for i, agent in enumerate(sorted(AGENTS), 1)]}

def _trace():
    return {"schema": "agentforge.v41.p2-runtime-proof/1", "invocations": [
        {"task_id": record["task_id"], "agent": record["agent"],
         "runtime": "SafeRepairRuntime", "status": "SUCCESS", "attempts": 1,
         "verification": [{"argv": ["node", "--test", "verification/test.js"],
                           "returncode": 0, "success": True}], "diagnoses": []}
        for record in _protocol()["task_runs"]]}

def test_4_agents_must_have_actual_p2_calls():
    good = evaluate_runtime_trace(_trace(), _protocol())
    assert good["status"] == "PASS" and good["executions"] == 4
    assert good["production_release_authorized"] is False

@pytest.mark.parametrize("mutation,error", [
    (lambda x: x["invocations"].pop(), "FOUR_AGENTS_DID_NOT_EXECUTE_P2"),
    (lambda x: x["invocations"][0].update(runtime="LiveCodingRuntime"), "UNTRUSTED_P2_INVOCATION"),
    (lambda x: x["invocations"][0].update(verification=[]), "INDEPENDENT_VERIFICATION_NOT_EXECUTED"),
    (lambda x: x["invocations"][0]["verification"][0].update(returncode=1), "VERIFICATION_RESULT_MALFORMED"),
    (lambda x: x["invocations"][0]["verification"][0].update(returncode=1,success=False), "SUCCESS_WITH_FAILED_VERIFICATION"),
    (lambda x: x["invocations"][0].update(task_id="TASK-FAKE"), "P2_EXECUTIONS_DO_NOT_MATCH_TASK_RECORDS"),
    (lambda x: x["invocations"][0].update(attempts=0), "UNTRUSTED_P2_INVOCATION"),
])
def test_forged_runtime_proof_never_passes(mutation, error):
    trace = _trace()
    mutation(trace)
    verdict = evaluate_runtime_trace(trace, _protocol())
    assert verdict["status"] == "BLOCKED" and error in verdict["issues"]

def test_missing_and_symlink_trace_fail_closed(tmp_path):
    absent = tmp_path / "nonexistent.json"
    assert verify_trace_file(absent, _protocol())["status"] == "BLOCKED"
    real = tmp_path / "ok.json"
    real.write_text(json.dumps(_trace()))
    link = tmp_path / "symlink.json"
    link.symlink_to(real)
    assert verify_trace_file(link, _protocol())["status"] == "BLOCKED"
    assert verify_trace_file(real, _protocol())["status"] == "PASS"

def test_instrument_wraps_actual_execute():
    path = ROOT / "scripts/v41_instrumented_cli.py"
    spec = importlib.util.spec_from_file_location("v41_instrument_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    events = []
    task = SimpleNamespace(id="TASK-1", assigned_agent="backend")
    runtime = SimpleNamespace(_latest_results=[SimpleNamespace(argv=["mvn", "test"], returncode=0, success=True)],
                              diagnoses=[], _attempts_seen=1)
    def original(self, t, ctx, check, feedback):
        assert t is task
        return SimpleNamespace(status="SUCCESS", attempts=1)
    returned = mod.instrument(original, events)(runtime, task, [], [])
    assert returned.status == "SUCCESS"
    assert events[0]["agent"] == "backend" and events[0]["verification"][0]["success"]

def test_instrument_rejects_unsafe_artifact_paths(monkeypatch, tmp_path):
    path = ROOT / "scripts/v41_instrumented_cli.py"
    spec = importlib.util.spec_from_file_location("v41_instrument_test2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("AGENTFORGE_BENCHMARK_ARTIFACT_DIR", str(tmp_path / "wrong_name"))
    with pytest.raises(RuntimeError, match="UNSAFE_ARTIFACT"):
        mod._trace_destination()

def test_service_schema_prefix_and_no_local_environment(monkeypatch, tmp_path):
    assert _schema_for("1234", 2) == "agentforge_v41_1234_02"
    with pytest.raises(ValueError):
        _schema_for("x; DROP DATABASE production", 1)
    with pytest.raises(ValueError):
        _schema_for("1234", 4)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    result = check_java_service(tmp_path, tmp_path / "reports", round_index=1,
                                run_id="1234", trusted_java=ROOT / "benchmarks/v41_trusted/TrustedPointsExactlyOnceTest.java")
    assert result["status"] == "FAIL" and "GITHUB_ACTIONS" in result["reason"]

def _mock_snapshot(tmp_path):
    root = tmp_path / "generated"
    (root / "server/src/main/java").mkdir(parents=True)
    (root / "server/pom.xml").write_text("<project/>")
    sql = root / "database/migrations/V980100__points.sql"
    sql.parent.mkdir(parents=True)
    sql.write_text("CREATE TABLE points_account(user_id BIGINT PRIMARY KEY);\n")
    return root

def test_service_gate_runs_trusted_junit_only_in_copy(tmp_path, monkeypatch):
    import agentforge.v41.service_gate as gate
    root = _mock_snapshot(tmp_path)
    calls = []
    def fake_run(argv, *, cwd, env, timeout, stdin=None):
        calls.append((argv, str(cwd), stdin))
        assert "AGENTFORGE_LLM_API_KEY" not in env
        assert "AGENTFORGE_V41_ATTEST_KEY" not in env
        assert "AGENTFORGE_V20_MYSQL_PASSWORD" in env
        if argv[0] == 'mvn':
            assert (Path(cwd) / "server/src/test/java/com/agentforge/shop/points/TrustedPointsExactlyOnceTest.java").is_file()
            assert "-Dtest=TrustedPointsExactlyOnceTest" in argv
        return {"returncode": 0, "stdout": "", "stderr": ""}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("AGENTFORGE_V20_MYSQL_PASSWORD", "isolated-test-password")
    monkeypatch.setenv("AGENTFORGE_LLM_API_KEY", "THIS_MUST_NOT_REACH_UNTRUSTED_MAVEN")
    monkeypatch.setenv("AGENTFORGE_V41_ATTEST_KEY", "THIS_MUST_NOT_REACH_UNTRUSTED_MAVEN")
    monkeypatch.setattr(gate, "_run", fake_run)
    report = tmp_path / "report"
    result = gate.check_java_service(root, report, round_index=1, run_id="101",
                                    trusted_java=ROOT / "benchmarks/v41_trusted/TrustedPointsExactlyOnceTest.java")
    assert result["status"] == "PASS"
    assert not (root / "server/src/test").exists()
    assert [x[0][0] for x in calls] == ["mysql", "mysql", "mvn", "mysql"]
    assert json.loads((report / "v41_java_service_gate.log").read_text())["result"] == result

def test_service_gate_maven_failure_cannot_be_green(tmp_path, monkeypatch):
    import agentforge.v41.service_gate as gate
    root = _mock_snapshot(tmp_path)
    def fake_run(argv, *, cwd, env, timeout, stdin=None):
        fail = argv[0] == "mvn"
        return {"returncode": 1 if fail else 0, "stdout": "", "stderr": "compilation error" if fail else ""}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("AGENTFORGE_V20_MYSQL_PASSWORD", "root")
    monkeypatch.setattr(gate, "_run", fake_run)
    result = gate.check_java_service(root, tmp_path / "out", round_index=2, run_id="12",
                                    trusted_java=ROOT / "benchmarks/v41_trusted/TrustedPointsExactlyOnceTest.java")
    assert result["status"] == "FAIL" and "JAVA_SERVICE_BEHAVIOR_FAILED" in result["reason"]

def test_service_gate_cleanup_failure_cannot_be_green(tmp_path, monkeypatch):
    import agentforge.v41.service_gate as gate
    root = _mock_snapshot(tmp_path)
    def fake_run(argv, *, cwd, env, timeout, stdin=None):
        fail = stdin and "DROP DATABASE" in stdin
        return {"returncode": 1 if fail else 0, "stdout": "", "stderr": "cleanup failed" if fail else ""}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("AGENTFORGE_V20_MYSQL_PASSWORD", "root")
    monkeypatch.setattr(gate, "_run", fake_run)
    result = gate.check_java_service(root, tmp_path / "out", round_index=1, run_id="13",
                                    trusted_java=ROOT / "benchmarks/v41_trusted/TrustedPointsExactlyOnceTest.java")
    assert result["status"] == "FAIL" and "CLEANUP_FAILED" in result["reason"]

def _attestation_fixture(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    records = []
    for i in (1, 2, 3):
        folder = root / f"round_{i:02d}"
        folder.mkdir()
        trace = _trace()
        protocol = _protocol()
        verified = evaluate_runtime_trace(trace, protocol)
        gate = {"name": "java_mysql_service_exactly_once", "status": "PASS", "exit_code": 0,
                "trusted_test_executed": True, "reason": "PASS"}
        record = {"round": i, "status": "PASS", "stage": "passed", "v41_p2_executed": verified,
                  "v41_service_gate": gate}
        stages = [{"step": x, "returncode": 0} for x in ("create", "migrate", "trusted_java_maven", "cleanup")]
        for filename, value in (("v20_runner_stdout.txt", protocol),
                                ("p2_runtime_proof.json", trace), ("v20_result.json", record),
                                ("v41_java_service_gate.log", {"result": gate, "stages": stages})):
            (folder / filename).write_text(json.dumps(value))
        records.append(record)
    (root / "summary.json").write_text(json.dumps({"overall": "PASS", "rounds_required": 3,
        "rounds_passed": 3, "v41_mode": "P2_EXECUTED_JAVA_EXACTLY_ONCE_GATE", "results": records}))
    p1 = tmp_path / "p1-manifest.json"
    p1.write_text('{"fake":"P1 checked by monkeypatch only"}')
    profile = tmp_path / "profile.yaml"
    profile.write_text('test: only\n')
    return root, p1, profile

def test_v41_signature_binds_new_behavior_and_p1(tmp_path, monkeypatch):
    root, p1, profile = _attestation_fixture(tmp_path)
    monkeypatch.setattr(attestation, "_verify_p1", lambda *args, **kwargs: None)
    args = {"run_id": 251, "commit": "a"*40, "model": "deepseek-test",
            "p1_key": b'p'*32, "v41_key": b'v'*32}
    sig = attestation.create_attestation(root, p1, profile, **args)
    assert attestation.verify_attestation(sig, root, p1, profile, **args)["independent_verified"] is True
    assert attestation.verify_attestation(sig, root, p1, profile, **{**args, "run_id": 252})["status"] == "BLOCKED"
    assert attestation.verify_attestation(sig, root, p1, profile, **{**args, "commit": "b"*40})["status"] == "BLOCKED"
    assert attestation.verify_attestation(sig, root, p1, profile, **{**args, "v41_key": b'w'*32})["status"] == "BLOCKED"
    (root / "round_01/p2_runtime_proof.json").write_text(json.dumps({"schema":"fake"}))
    assert attestation.verify_attestation(sig, root, p1, profile, **args)["status"] == "BLOCKED"

def test_signed_v41_cannot_upgrade_service_failure(tmp_path, monkeypatch):
    root, p1, profile = _attestation_fixture(tmp_path)
    monkeypatch.setattr(attestation, "_verify_p1", lambda *args, **kwargs: None)
    record_path = root / "round_02/v20_result.json"
    record = json.loads(record_path.read_text())
    record["v41_service_gate"]["status"] = "FAIL"
    record_path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="JAVA_SERVICE_GATE_FAILED|ROUND_SUMMARY_MISMATCH"):
        attestation.create_attestation(root, p1, profile, run_id=1, commit='a'*40,
                                       model='deepseek',p1_key=b'p'*32,v41_key=b'v'*32)

def test_artifact_symlink_denied(tmp_path):
    root,p1,profile=_attestation_fixture(tmp_path)
    path = root / 'round_01/p2_runtime_proof.json'
    source = tmp_path / 'original.json'
    source.write_bytes(path.read_bytes())
    path.unlink();path.symlink_to(source)
    with pytest.raises(ValueError,match='SYMLINK'):
        attestation.safe_read(root,'round_01/p2_runtime_proof.json')

def test_failed_schema_creation_does_not_drop_other_schema(tmp_path, monkeypatch):
    import agentforge.v41.service_gate as gate
    root = _mock_snapshot(tmp_path)
    calls = []
    def fake_run(argv, *, cwd, env, timeout, stdin=None):
        calls.append(stdin or 'mvn')
        return {"returncode": 1, "stdout": "", "stderr": "schema exists"}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("AGENTFORGE_V20_MYSQL_PASSWORD", "root")
    monkeypatch.setattr(gate, "_run", fake_run)
    result = gate.check_java_service(root, tmp_path / 'out', round_index=1, run_id='177',
                                    trusted_java=ROOT / 'benchmarks/v41_trusted/TrustedPointsExactlyOnceTest.java')
    assert result['status'] == 'FAIL' and result['reason'] == 'SCHEMA_CREATE_FAILED'
    assert len(calls) == 1
    assert not any('DROP DATABASE' in v for v in calls)
