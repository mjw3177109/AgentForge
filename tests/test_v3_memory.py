"""P3 offline security + true P1/P2 integration tests; no external credentials."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from agentforge.evidence_v3 import EXPECTED_V20_GATES, attest, collect_v20
from agentforge.evidence_v3.v20 import SNAPSHOT_FILES
from agentforge.memory_v3 import (
    MemorySafetyError, MemoryStore, trusted_profile_hash, validate_diagnosis,
)

PROJECT = "mjw3177109/AgentForge"
OTHER = "anotherowner/anotherrepo"
COMMIT = "a" * 40
DIAG = {"category": "JAVA_TYPE_ERROR", "retryable": True, "fingerprint": "b" * 20,
        "guidance": "Untrusted P2 output, never copied into recommendations"}
SECRET = b"Independent-test-secret-not-for-production!" * 2
MODEL = "deepseek-test"
KEY_ID = "trusted-ci"


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    path.write_text(value, encoding="utf-8")


def fixture(tmp_path: Path, *, fail_round: int = 0):
    root = tmp_path / "artifacts"
    profile = tmp_path / "profile.yaml"
    write(profile, "agents: {}\n")
    results = []
    for round_number in (1, 2, 3):
        folder = root / f"round_{round_number:02d}"
        failed = round_number == fail_round
        checks = []
        for gate_name in EXPECTED_V20_GATES:
            checks.append({"name": gate_name, "status": "PASS", "exit_code": 0})
            if gate_name == "mysql_concurrent_ledger_uniqueness":
                write(folder / f"{gate_name}.log", {
                    "seed": {"exit_code": 0},
                    "inserts": [{"exit_code": 0}, {"exit_code": 1, "stderr": "ERROR 1062 Duplicate entry"}],
                    "count": {"exit_code": 0, "stdout": "1\n"}})
            else:
                write(folder / f"{gate_name}.log", "exit_code=0\n" + (
                    "points_account\npoints_ledger\n" if gate_name == "mysql_schema" else ""))
        for source in SNAPSHOT_FILES:
            write(folder / "generated-repo" / source, f"sample {round_number} {source}\n")
        record = {"round": round_number, "status": "FAIL" if failed else "PASS",
                  "stage": "maven" if failed else "passed",
                  "reason": "Java compile rejected" if failed else "All verified",
                  "benchmark_exit_code": 2 if failed else 0,
                  "initial_agents": ["database", "backend", "miniapp", "admin"],
                  "repair_agents": [], "review_status": "APPROVE", "gates": checks}
        write(folder / "v20_result.json", record)
        write(folder / "v20_runner_stdout.txt", {
            "status": "SUCCESS", "review": {"status": "APPROVE", "evidence": ["TASK-1"]},
            "pr_url": None,
            "task_runs": [
                {"agent": agent, "task_id": f"TASK-{i}", "status": "SUCCESS",
                 "commit": COMMIT, "message": "done"}
                for i, agent in enumerate(("database", "backend", "miniapp", "admin"), 1)
            ]})
        write(folder / "v20_runner_stderr.txt", "")
        results.append(record)
    write(root / "summary.json", {
        "overall": "FAIL" if fail_round else "PASS", "rounds_required": 3,
        "rounds_passed": 2 if fail_round else 3,
        "all_reviewer_approve": True, "results": results})
    return root, profile


def signed(root: Path, profile: Path, *, run_id: int = 145):
    unsigned = collect_v20(artifact_dir=root, trusted_profile=profile,
                           run_id=run_id, commit_sha=COMMIT, model_id=MODEL)
    return attest(unsigned, secret=SECRET, key_id=KEY_ID)


def import_run(store, root, profile, *, run_id=145, envelope=None, project=PROJECT,
               commit=COMMIT, secret=SECRET, model=MODEL):
    return store.import_attested_run(
        project=project, envelope=envelope or signed(root, profile, run_id=run_id),
        artifact_dir=root, trusted_profile=profile, expected_run_id=run_id,
        expected_commit_sha=commit, expected_model_id=model,
        expected_key_id=KEY_ID, secret=secret)


@pytest.fixture
def memory(tmp_path):
    store = MemoryStore(tmp_path / "agentforge-memory.sqlite3")
    store.initialize()
    return store


def observe(store, profile, *, project=PROJECT, diagnosis=DIAG, source="diagnostic-01"):
    return store.observe_diagnosis(project=project,
        profile_sha256=trusted_profile_hash(profile), diagnosis=diagnosis, source_id=source)


def predeclare(store, profile, *, project=PROJECT, run_id=145, commit=COMMIT):
    return store.predeclare_trial(project=project, profile_sha256=trusted_profile_hash(profile),
        run_id=run_id, commit_sha=commit, fingerprint=DIAG["fingerprint"],
        strategy_id="java-declared-type-check")


def recommendation(store, profile, project=PROJECT, diagnosis=DIAG):
    return store.recommend(project=project, profile_sha256=trusted_profile_hash(profile),
                           diagnosis=diagnosis)


def test_init_is_explicit_and_read_paths_never_create_db(tmp_path):
    store = MemoryStore(tmp_path / "db.sqlite3")
    with pytest.raises(MemorySafetyError, match="not initialized"):
        store.history(project=PROJECT)
    assert not store.path.exists()
    store.initialize()
    assert store.path.is_file()
    assert store.path.stat().st_mode & 0o077 == 0
    assert sqlite3.connect(store.path).execute("PRAGMA user_version").fetchone()[0] == 1
    store.initialize()


def test_observed_diagnosis_is_quarantined_never_verified(memory, tmp_path):
    _, profile = fixture(tmp_path)
    input_data = {**DIAG, "stdout": "DO_NOT_STORE_API_KEY", "secret": "DO_NOT_STORE_API_KEY"}
    observed = observe(memory, profile, diagnosis=input_data)
    assert observed["status"] == "OBSERVED_UNVERIFIED"
    assert observed["recorded"] is True
    assert observe(memory, profile, diagnosis=input_data)["recorded"] is False
    assert b"DO_NOT_STORE_API_KEY" not in memory.path.read_bytes()


def test_known_catalog_only_and_never_return_untrusted_guidance(memory, tmp_path):
    _, profile = fixture(tmp_path)
    res = recommendation(memory, profile)
    assert res["status"] == "ADVISORY_ONLY"
    assert len(res["recommendations"]) == 2
    assert all(x["evidence_level"] == "STATIC_CATALOG" for x in res["recommendations"])
    assert DIAG["guidance"] not in res["recommendations"][0]["guidance"]
    assert "write_scope" not in str(res)


@pytest.mark.parametrize("category", ["VERIFICATION_SCOPE_GAP", "TIMEOUT", "ENVIRONMENT", "JAVA_VERIFICATION_GAP", "NONE"])
def test_security_and_environment_categories_never_produce_repair_recommendation(memory, tmp_path, category):
    _, profile = fixture(tmp_path)
    report = recommendation(memory, profile, diagnosis={
        "category": category, "retryable": False, "fingerprint": DIAG["fingerprint"]})
    assert report["status"] == "BLOCKED_FOR_AUTOREPAIR"
    assert report["recommendations"] == []


@pytest.mark.parametrize("broken", [
    {"category": "ADMIN_OVERRIDE", "retryable": True, "fingerprint": "a"*20},
    {"category": "JAVA_TYPE_ERROR", "retryable": True, "fingerprint": "bad"},
    {"category": "JAVA_TYPE_ERROR", "retryable": False, "fingerprint": "a"*20},
    {"category": "TIMEOUT", "retryable": True, "fingerprint": "a"*20},
    {"category": "JAVA_TYPE_ERROR", "retryable": 1, "fingerprint": "a"*20},
])
def test_malicious_diagnoses_rejected(broken):
    with pytest.raises(MemorySafetyError):
        validate_diagnosis(broken)


def test_predeclare_must_match_same_project_profile_and_known_strategy(memory, tmp_path):
    _, profile = fixture(tmp_path)
    with pytest.raises(MemorySafetyError):
        predeclare(memory, profile)
    observe(memory, profile)
    assert predeclare(memory, profile)["status"] == "PENDING_UNVERIFIED"
    with pytest.raises(MemorySafetyError):
        predeclare(memory, profile)
    with pytest.raises(MemorySafetyError):
        memory.predeclare_trial(project=PROJECT, profile_sha256=trusted_profile_hash(profile),
            run_id=200, commit_sha=COMMIT, fingerprint=DIAG["fingerprint"],
            strategy_id="dangerous-write-tests")
    with pytest.raises(MemorySafetyError):
        predeclare(memory, profile, project=OTHER, run_id=200)


def test_independent_three_round_success_associates_not_proves_strategy(memory, tmp_path):
    root, profile = fixture(tmp_path)
    observe(memory, profile)
    predeclare(memory, profile)
    # Re-import the identical signed envelope. Re-signing later changes signed
    # evidence bytes and must still be blocked by the replay-security check.
    original_envelope = signed(root, profile)
    result = import_run(memory, root, profile, envelope=original_envelope)
    assert result["status"] == "IMPORTED_PASS"
    assert result["rounds_passed"] == 3
    assert result["strategy_trial_linked"]
    rec = recommendation(memory, profile)
    item = next(x for x in rec["recommendations"] if x["strategy_id"] == "java-declared-type-check")
    assert item["associated_passes"] == 1
    assert item["associated_failures"] == 0
    assert item["evidence_level"] == "HISTORICAL_ASSOCIATION"
    assert rec["status"] == "ADVISORY_ONLY"
    assert import_run(memory, root, profile, envelope=original_envelope)["recorded"] is False
    assert sum(x["associated_passes"] for x in recommendation(memory, profile)["recommendations"]) == 1


def test_signed_two_of_three_fail_imports_only_as_failure(memory, tmp_path):
    root, profile = fixture(tmp_path, fail_round=1)
    observe(memory, profile)
    predeclare(memory, profile)
    result = import_run(memory, root, profile)
    assert result["status"] == "IMPORTED_FAIL"
    assert result["rounds_passed"] == 2
    item = next(x for x in recommendation(memory, profile)["recommendations"]
                if x["strategy_id"] == "java-declared-type-check")
    assert item["associated_passes"] == 0
    assert item["associated_failures"] == 1
    assert item["ranking_heuristic"] < 0.5


def test_failed_evidence_without_completed_trusted_attestation_is_rejected(memory, tmp_path):
    root, profile = fixture(tmp_path, fail_round=2)
    envelope = signed(root, profile)
    envelope["assessment"]["rounds_passed"] = 3
    with pytest.raises(MemorySafetyError, match="verification blocked"):
        import_run(memory, root, profile, envelope=envelope)
    assert memory.history(project=PROJECT)["runs"] == []


def test_signed_input_mutation_rejected_and_no_memory(memory, tmp_path):
    root, profile = fixture(tmp_path)
    envelope = signed(root, profile)
    (root / "round_02" / "maven.log").write_text("exit_code=0\nTAMPER")
    with pytest.raises(MemorySafetyError):
        import_run(memory, root, profile, envelope=envelope)
    assert memory.history(project=PROJECT)["runs"] == []


def test_wrong_signature_key_commit_model_replay_blocked(memory, tmp_path):
    root, profile = fixture(tmp_path)
    envelope = signed(root, profile)
    for options in ({"secret": b"z"*48}, {"commit": "f"*40}, {"model": "other-model"}):
        with pytest.raises(MemorySafetyError):
            import_run(memory, root, profile, envelope=envelope, **options)
    assert memory.history(project=PROJECT)["runs"] == []


def test_cannot_register_strategy_retrospectively(memory, tmp_path):
    root, profile = fixture(tmp_path)
    assert import_run(memory, root, profile)["status"] == "IMPORTED_PASS"
    observe(memory, profile)
    with pytest.raises(MemorySafetyError, match="retrospectively"):
        predeclare(memory, profile)
    assert sum(x["associated_passes"] for x in recommendation(memory, profile)["recommendations"]) == 0


def test_cross_project_profile_and_fingerprint_do_not_leak(memory, tmp_path):
    root, profile = fixture(tmp_path)
    observe(memory, profile)
    predeclare(memory, profile)
    import_run(memory, root, profile)
    new_profile = tmp_path / "other-profile.yaml"
    write(new_profile, "different: execution ceiling\n")
    assert all(x["associated_passes"] == 0 for x in recommendation(memory, profile, project=OTHER)["recommendations"])
    assert all(x["associated_passes"] == 0 for x in recommendation(memory, new_profile)["recommendations"])
    different = {**DIAG, "fingerprint": "c"*20}
    assert all(x["associated_passes"] == 0 for x in recommendation(memory, profile, diagnosis=different)["recommendations"])
    with pytest.raises(MemorySafetyError):
        import_run(memory, root, new_profile)


def test_mismatched_predeclared_commit_rolls_back_import_atomically(memory, tmp_path):
    root, profile = fixture(tmp_path)
    observe(memory, profile)
    predeclare(memory, profile, commit="f"*40)
    with pytest.raises(MemorySafetyError, match="different commit"):
        import_run(memory, root, profile)
    assert memory.history(project=PROJECT)["runs"] == []


def test_run_id_duplicate_conflicting_evidence_blocked(memory, tmp_path):
    root, profile = fixture(tmp_path)
    import_run(memory, root, profile)
    write(root / "round_01" / "maven.log", "exit_code=0\nUPDATED")
    # Re-signing changed output intentionally produces a different envelope hash.
    changed = signed(root, profile)
    with pytest.raises(MemorySafetyError, match="conflicting"):
        import_run(memory, root, profile, envelope=changed)
    assert len(memory.history(project=PROJECT)["runs"]) == 1


def test_symlink_db_is_rejected(tmp_path):
    target = tmp_path / "target.sqlite3"
    target.write_bytes(b"not a database")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(target)
    with pytest.raises(MemorySafetyError, match="symlink"):
        MemoryStore(link)


def test_hardlinked_db_is_rejected(tmp_path):
    p = tmp_path / "a.sqlite3"
    MemoryStore(p).initialize()
    twin = tmp_path / "b.sqlite3"
    import os
    os.link(p, twin)
    with pytest.raises(MemorySafetyError, match="hardlinked"):
        MemoryStore(p)


@pytest.mark.parametrize("project", ["../evil", "owner/../project", "owner/repo/other", "/abs/repo", "./repo"])
def test_project_paths_must_be_exact_repos(memory, project):
    with pytest.raises(MemorySafetyError):
        memory.history(project=project)


def test_read_only_query_does_not_update_database(memory, tmp_path):
    _, profile = fixture(tmp_path)
    before = memory.path.stat().st_mtime_ns
    recommendation(memory, profile)
    memory.history(project=PROJECT)
    assert memory.path.stat().st_mtime_ns == before


def test_p2_real_diagnosis_to_p3_observation(memory, tmp_path):
    """P3 accepts P2's actual classifier without importing raw logs into memory."""
    from agentforge.repair_v3 import diagnose_verification
    from agentforge.coding import VerificationResult
    _, profile = fixture(tmp_path)
    source = "PointsService.java:[93,52] incompatible types: java.util.Optional<java.lang.Long> cannot be converted to long"
    d = diagnose_verification([VerificationResult(
        argv=["mvn", "test"], returncode=1, success=False, stdout="", stderr=source)])
    assert d.category == "JAVA_TYPE_ERROR"
    observed = observe(memory, profile, diagnosis={
        "category": d.category, "fingerprint": d.fingerprint,
        "retryable": d.retryable, "guidance": d.guidance})
    assert observed["status"] == "OBSERVED_UNVERIFIED"
    assert memory.recommend(project=PROJECT, profile_sha256=trusted_profile_hash(profile),
                            diagnosis={"category": d.category, "fingerprint": d.fingerprint,
                                       "retryable": d.retryable})["recommendations"][0]["strategy_id"] == "java-declared-type-check"


def test_cli_init_observe_recommend_history_and_no_shell_action(tmp_path, capsys):
    script = Path(__file__).resolve().parents[1] / "scripts" / "v3_memory.py"
    spec = importlib.util.spec_from_file_location("memory_cli", script)
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    _, profile = fixture(tmp_path)
    db = tmp_path / "cli.sqlite3"
    diagnosis_file = tmp_path / "diagnosis.json"
    write(diagnosis_file, DIAG)
    def go(*argv):
        assert cli.main(["--db", str(db), *argv]) == 0
        return json.loads(capsys.readouterr().out)
    assert go("init")["status"] == "INITIALIZED"
    assert go("observe", "--project", PROJECT, "--profile", str(profile),
              "--diagnosis", str(diagnosis_file), "--source-id", "round01")["recorded"]
    assert go("recommend", "--project", PROJECT, "--profile", str(profile),
              "--diagnosis", str(diagnosis_file))["status"] == "ADVISORY_ONLY"
    assert go("history", "--project", PROJECT)["runs"] == []


def test_repeated_failed_strategy_suppressed_with_alternative(memory, tmp_path):
    root, profile = fixture(tmp_path, fail_round=1)
    observe(memory, profile)
    for run_id in (145, 146):
        predeclare(memory, profile, run_id=run_id)
        assert import_run(memory, root, profile, run_id=run_id)["status"] == "IMPORTED_FAIL"
    rec = recommendation(memory, profile)
    ids = [x["strategy_id"] for x in rec["recommendations"]]
    assert "java-declared-type-check" not in ids
    assert "java-optional-boundary-review" in ids


def test_existing_foreign_sqlite_never_modified(tmp_path):
    location = tmp_path / "foreign.db"
    with sqlite3.connect(location) as connection:
        connection.execute("CREATE TABLE important_data (secret TEXT)")
        connection.execute("INSERT INTO important_data VALUES ('keep')")
    with pytest.raises(MemorySafetyError, match="Unrecognized"):
        MemoryStore(location).initialize()
    with sqlite3.connect(location) as connection:
        assert connection.execute("SELECT secret FROM important_data").fetchone()[0] == "keep"
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name='runs'").fetchone()


def test_conflicting_classification_same_fingerprint_denied(memory, tmp_path):
    _, profile = fixture(tmp_path)
    observe(memory, profile)
    incompatible = {"category": "JAVA_COMPILATION", "fingerprint": DIAG["fingerprint"],
                    "retryable": True}
    with pytest.raises(MemorySafetyError, match="Conflicting"):
        observe(memory, profile, diagnosis=incompatible, source="diagnostic-02")
