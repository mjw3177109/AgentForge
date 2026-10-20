"""P4 failure-closed integration tests; all checks are local, no external LLM."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import shutil

from agentforge.acceptance_v3 import (
    inspect_components, inspect_v20_history, validate_attested_run,
    validate_offline_matrix, COMPONENT_FILES,
)
from agentforge.coding import VerificationResult
from agentforge.governance import ProposedChange, assess
from agentforge.repair_v3 import diagnose_verification
from agentforge.memory_v3 import MemoryStore, trusted_profile_hash
from agentforge.evidence_v3 import collect_v20, attest
from test_v3_evidence import create_fixture, SECRET, COMMIT, MODEL, RUN_ID


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/v3_p4_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("v3_p4_acceptance_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
cli = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cli)


def _record(root: Path, value):
    p = root / "signed.json"
    p.write_text(json.dumps(value), encoding="utf-8")
    return p


def _verified(root, profile, manifest, **replacements):
    args = {
        "manifest": manifest, "artifacts": root, "trusted_profile": profile,
        "expected_run_id": RUN_ID, "expected_commit": COMMIT,
        "expected_model": MODEL, "expected_key_id": "trusted-ci", "secret": SECRET,
    }
    args.update(replacements)
    return validate_attested_run(**args)


def test_successful_synthetic_v20_can_only_mark_live_evidence_verified(tmp_path):
    root, profile = create_fixture(tmp_path)
    signed = attest(collect_v20(artifact_dir=root, run_id=RUN_ID,
                                commit_sha=COMMIT, model_id=MODEL,
                                trusted_profile=profile), secret=SECRET, key_id="trusted-ci")
    manifest = _record(tmp_path, signed)
    report = _verified(root, profile, manifest)
    assert report["status"] == "INDEPENDENT_LIVE_3_OF_3_VERIFIED"
    assert report["production_release_authorized"] is False
    assert report["automated_merge_authorized"] is False
    assert len(report["rounds"]) == 3
    assert all(r["assessment"] == "PASS" for r in report["rounds"])


def test_two_of_three_never_verifies(tmp_path):
    root, profile = create_fixture(tmp_path, fail_round=1)
    historic = inspect_v20_history(root)
    assert historic["status"] == "REPORTED_FAIL"
    assert historic["reported_rounds_passed"] == 2
    signed = attest(collect_v20(artifact_dir=root, run_id=RUN_ID,
                                commit_sha=COMMIT, model_id=MODEL,
                                trusted_profile=profile), secret=SECRET, key_id="trusted-ci")
    report = _verified(root, profile, _record(tmp_path, signed))
    assert report["status"] == "BLOCKED"
    assert report["production_release_authorized"] is False


def test_wrong_pinned_run_and_commit_block(tmp_path):
    root, profile = create_fixture(tmp_path)
    signed = attest(collect_v20(artifact_dir=root, run_id=RUN_ID,
                                commit_sha=COMMIT, model_id=MODEL,
                                trusted_profile=profile), secret=SECRET, key_id="trusted-ci")
    manifest = _record(tmp_path, signed)
    assert _verified(root, profile, manifest, expected_run_id=RUN_ID + 1)["status"] == "BLOCKED"
    assert _verified(root, profile, manifest, expected_commit="e"*40)["status"] == "BLOCKED"
    assert _verified(root, profile, manifest, secret=b"x"*48)["status"] == "BLOCKED"
    assert _verified(root, profile, manifest, expected_model="different-model")["status"] == "BLOCKED"


def test_modify_log_after_signature_blocks(tmp_path):
    root, profile = create_fixture(tmp_path)
    signed = attest(collect_v20(artifact_dir=root, run_id=RUN_ID,
                                commit_sha=COMMIT, model_id=MODEL,
                                trusted_profile=profile), secret=SECRET, key_id="trusted-ci")
    manifest = _record(tmp_path, signed)
    with (root / "round_02" / "maven.log").open("a", encoding="utf-8") as f:
        f.write("\nTAMPER")
    assert _verified(root, profile, manifest)["status"] == "BLOCKED"


def test_legacy_history_is_diagnostic_not_authenticated(tmp_path):
    root, _ = create_fixture(tmp_path)
    got = inspect_v20_history(root)
    assert got["status"] == "ELIGIBLE_FOR_INDEPENDENT_P1_VERIFICATION"
    assert got["authenticated"] is False
    assert got["production_release_authorized"] is False
    (root / "round_03" / "v20_result.json").unlink()
    assert inspect_v20_history(root)["status"] == "BLOCKED"


def test_component_inspection_refuses_missing_and_symlinks(tmp_path):
    assert inspect_components(tmp_path)["status"] == "BLOCKED"
    for rel in COMPONENT_FILES:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("fixture")
    target = tmp_path / COMPONENT_FILES[0]
    target.unlink()
    target.symlink_to(tmp_path / COMPONENT_FILES[1])
    assert "SYMLINK_IN_EVIDENCE_PATH" in str(inspect_components(tmp_path)["issues"])


def test_matrix_reports_always_need_trusted_external_job_status():
    reports = {v: {"status": "OFFLINE_SUITE_PASS", "python_minor": v,
                   "git_commit": COMMIT, "iterations_required": 3, "iterations_passed": 3}
               for v in ("3.11", "3.12")}
    result = validate_offline_matrix(reports, COMMIT)
    assert result["status"] == "UNAUTHENTICATED_CANDIDATE"
    assert result["requires_independent_github_job_verification"] is True
    assert result["production_release_authorized"] is False
    reports["3.12"]["iterations_passed"] = 2
    assert validate_offline_matrix(reports, COMMIT)["status"] == "BLOCKED"


def _mock_offline_repo(tmp_path):
    root = tmp_path
    paths = ["tests/test_v3_preflight.py", "tests/test_v3_evidence.py",
             "tests/test_v3_repair.py", "tests/test_v3_p2_installer.py",
             "tests/test_v3_memory.py", "tests/test_v3_p4_acceptance.py",
             "protocol_bundle/scripts/validate_protocol.py"]
    for rel in paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# test file\n")
    return root


def test_fixed_offline_suite_calls_six_checks_without_shell(tmp_path, monkeypatch):
    root = _mock_offline_repo(tmp_path)
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(tuple(argv))
        assert kwargs["shell"] is False
        assert kwargs["timeout"] <= 1800
        if argv[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout=COMMIT + "\n", stderr="")
        if "pytest" in argv:
            return SimpleNamespace(returncode=0, stdout="149 passed in 7.12s", stderr="")
        return SimpleNamespace(returncode=0, stdout="protocol OK", stderr="")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    result = cli.fixed_offline_suite(root, iterations=3, scope="full")
    assert result["status"] == "OFFLINE_SUITE_PASS"
    assert result["iterations_passed"] == 3
    assert len(calls) == 7  # 3 x (pytest + protocol) and git rev-parse
    assert result["production_release_authorized"] is False


def test_fixed_offline_suite_rejects_skips_and_missing_tests(tmp_path, monkeypatch):
    root = _mock_offline_repo(tmp_path)
    def skipped(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout="148 passed, 1 skipped in 1.2s", stderr="")
    monkeypatch.setattr(cli.subprocess, "run", skipped)
    result = cli.fixed_offline_suite(root, iterations=3, scope="v3-smoke")
    assert result["status"] == "OFFLINE_SUITE_FAIL"
    assert result["iterations_passed"] == 0
    (root / "tests/test_v3_memory.py").unlink()
    assert cli.fixed_offline_suite(root, iterations=1, scope="v3-smoke")["status"] == "BLOCKED"


def test_p0_p2_p3_cross_module_flow_keeps_test_scope_denied(tmp_path):
    trusted = SimpleNamespace(read_scope=["server/**"],
                              write_scope=["server/src/main/**"], deny_scope=[])
    outcome = assess(repo_root=tmp_path,
                     task=ProposedChange("TASK-1", ("server/src/test/java/BadTest.java",)),
                     agent="backend", trusted_profile=trusted)
    assert outcome.status == "BLOCKED"
    diagnosis = diagnose_verification([VerificationResult(
        argv=["mvn", "test"], returncode=1, stdout="",
        stderr="PointsService.java:[93,19] incompatible types: Optional<Long> cannot be converted to long",
        success=False)])
    assert diagnosis.category == "JAVA_TYPE_ERROR"
    db = MemoryStore(tmp_path.parent / (tmp_path.name + "_p4-memory.sqlite3"))
    db.initialize()
    profile = tmp_path / "profile.yaml"
    profile.write_text("v: 1\n")
    memo = db.observe_diagnosis(project="mjw3177109/AgentForge",
                                profile_sha256=trusted_profile_hash(profile),
                                diagnosis={"category": diagnosis.category,
                                           "retryable": diagnosis.retryable,
                                           "guidance": diagnosis.guidance,
                                           "fingerprint": diagnosis.fingerprint},
                                source_id="local-p4-test")
    assert memo["status"] == "OBSERVED_UNVERIFIED"
    assert outcome.status == "BLOCKED"  # memory cannot widen profile


def test_manual_workflow_has_no_unapproved_write_or_auto_paid_trigger():
    import yaml
    repo = Path(__file__).resolve().parents[1]
    workflow = repo / ".github/workflows/agentforge-v30-p4-acceptance.yml"
    data = yaml.load(workflow.read_text("utf-8"), Loader=yaml.BaseLoader)
    assert set(data["on"]) == {"workflow_dispatch"}
    assert data["permissions"] == {"contents": "read"}
    jobs = data["jobs"]
    assert set(jobs) == {"authorize", "offline", "live", "independent-attestation"}
    assert "AGENTFORGE_V3_EVIDENCE_KEY" not in jobs["live"].get("env", {})
    assert "AGENTFORGE_V3_EVIDENCE_KEY" in jobs["independent-attestation"]["env"]
    assert "AGENTFORGE_LLM_API_KEY" not in jobs["independent-attestation"].get("env", {})
