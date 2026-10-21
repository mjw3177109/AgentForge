"""V2.8 offline contract tests only: no systemd, DB, Worker or model execution."""
import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_django_v28_host_acceptance.py"
SPEC = importlib.util.spec_from_file_location("agentforge_v28_acceptance", SCRIPT)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
SHA = "a" * 40


@pytest.fixture
def preflight(tmp_path):
    path = tmp_path / "preflight.json"
    report = {
        "schema": "agentforge.django.v23.worker-preflight.v1",
        "mode": "dedicated",
        "ready_to_accept_candidate_only_jobs": True,
        "checks": [{"check": name, "passed": True, "failure_code": None}
                   for name in VERIFY.CHECK_NAMES],
        "checks_total": 13, "checks_passed": 13,
        "external_vm_independently_attested": False,
        "real_deepseek_tested": False,
        "production_release_authorized": False,
    }
    path.write_text(json.dumps(report))
    path.chmod(0o600)
    return path, report


def mocked_runner(*, sha=SHA, status="", bad_gate=None, exit_gate=None):
    def run(args, **kwargs):
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        assert "AGENTFORGE_LLM_API_KEY" not in kwargs["env"]
        if args[0] == "git":
            content = sha + "\n" if "rev-parse" in args else status
            return SimpleNamespace(returncode=0, stdout=content, stderr="")
        filename = Path(args[-1]).name
        mapping = {
            "check_django_v25_host.py": (
                "agentforge.django.v25.host-prerequisites.v1",
                "ready_for_unit_staging_only"),
            "check_django_v27_source_tree.py": (
                "agentforge.django.v27.source-tree-gate.v1",
                "ready_for_unit_staging_only"),
            "audit_django_v24_systemd_host.py": (
                "agentforge.django.v24.installed-systemd-audit.v1",
                "installed_units_match_reviewed_templates"),
        }
        schema, key = mapping[filename]
        return SimpleNamespace(
            returncode=2 if filename == exit_gate else 0,
            stdout=json.dumps({"schema": schema, key: filename != bad_gate,
                               "production_release_authorized": False}),
            stderr="PRIVATE_HOST_SECRET"
        )
    return run


def evaluate(path, **kwargs):
    return VERIFY.evaluate(preflight_path=path, expected_commit=SHA,
                           expected_uid=os.getuid(), runner=mocked_runner(),
                           repo=ROOT,
                           _fixture_ancestry_boundary=Path(path).parent, **kwargs)


def failures(report):
    return {check["check"]: check["failure_code"] for check in report["checks"]
            if not check["passed"]}


def test_synthetic_pass_is_only_operator_review_not_release(preflight):
    path, _ = preflight
    result = evaluate(path)
    assert result["host_acceptance_ready_for_operator_review_only"] is True
    assert result["checks_total"] == result["checks_passed"] == 6
    assert len(result["preflight_sha256"]) == 64
    assert result["external_vm_identity_attested"] is False
    assert result["remote_postgres_directly_probed_by_this_tool"] is False
    assert result["preflight_executed_by_this_tool"] is False
    assert result["worker_started_or_enabled"] is False
    assert result["model_credentials_read"] is False
    assert result["production_release_authorized"] is False
    assert str(path.parent) not in json.dumps(result)


@pytest.mark.parametrize("key,value", [
    ("mode", "ci-staging"),
    ("ready_to_accept_candidate_only_jobs", False),
    ("checks_passed", 12),
    ("checks_total", True),
    ("external_vm_independently_attested", True),
    ("production_release_authorized", True),
])
def test_rejects_invalid_or_misleading_preflight(preflight, key, value):
    path, report = preflight
    report[key] = value
    path.write_text(json.dumps(report))
    assert "fresh_dedicated_worker_preflight_13_of_13" in failures(evaluate(path))


def test_requires_all_13_named_checks_not_only_reported_count(preflight):
    path, report = preflight
    report["checks"][10]["passed"] = False
    report["checks"][10]["failure_code"] = "ACTIVE_OR_STALE_WORKER_LEASE_REQUIRES_OPERATOR"
    path.write_text(json.dumps(report))
    assert "fresh_dedicated_worker_preflight_13_of_13" in failures(evaluate(path))


def test_missing_duplicate_or_reordered_check_rejected(preflight):
    path, report = preflight
    report["checks"][0]["check"] = "dedicated_role"
    path.write_text(json.dumps(report))
    assert not evaluate(path)["host_acceptance_ready_for_operator_review_only"]


def test_duplicate_json_object_key_rejected(preflight):
    path, _ = preflight
    raw = path.read_text()
    path.write_text(raw.replace('"mode": "dedicated"',
                                '"mode": "dedicated", "mode": "dedicated"'))
    assert "fresh_dedicated_worker_preflight_13_of_13" in failures(evaluate(path))


def test_stale_future_untrusted_permission_and_symlink_rejected(preflight, tmp_path):
    path, _ = preflight
    path.chmod(0o644)
    assert not evaluate(path)["host_acceptance_ready_for_operator_review_only"]
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    assert not evaluate(link)["host_acceptance_ready_for_operator_review_only"]
    now = time.time()
    assert not evaluate(path, now=now + 301)["host_acceptance_ready_for_operator_review_only"]
    assert not evaluate(path, now=now - 10)["host_acceptance_ready_for_operator_review_only"]


def test_missing_preflight_is_a_release_blocker(tmp_path):
    report = evaluate(tmp_path / "not-here")
    assert report["host_acceptance_ready_for_operator_review_only"] is False
    assert "fresh_dedicated_worker_preflight_13_of_13" in failures(report)


def test_wrong_git_revision_and_dirty_worktree_are_blockers(preflight):
    path, _ = preflight
    for overrides, code in (
        ({"sha": "b" * 40}, "pinned_git_revision"),
        ({"status": " M scripts/example.py\n"}, "clean_worker_worktree"),
    ):
        result = VERIFY.evaluate(preflight_path=path, expected_commit=SHA,
                                 expected_uid=os.getuid(), repo=ROOT,
                                 _fixture_ancestry_boundary=path.parent,
                                 runner=mocked_runner(**overrides))
        assert code in failures(result)


def test_incorrect_expected_revision_is_rejected_without_run(preflight):
    path, _ = preflight
    result = VERIFY.evaluate(preflight_path=path, expected_commit="not-a-sha",
                             expected_uid=os.getuid(), repo=ROOT,
                             _fixture_ancestry_boundary=path.parent,
                             runner=mocked_runner())
    assert "pinned_git_revision" in failures(result)
    assert result["expected_commit"] is None


@pytest.mark.parametrize("name", [
    "check_django_v25_host.py", "check_django_v27_source_tree.py",
    "audit_django_v24_systemd_host.py",
])
def test_each_host_gate_failure_and_nonzero_exit_are_blockers(preflight, name):
    path, _ = preflight
    for runner in (mocked_runner(bad_gate=name), mocked_runner(exit_gate=name)):
        result = VERIFY.evaluate(preflight_path=path, expected_commit=SHA,
                                 expected_uid=os.getuid(), repo=ROOT,
                                 _fixture_ancestry_boundary=path.parent,
                                 runner=runner)
        assert not result["host_acceptance_ready_for_operator_review_only"]
        assert len(failures(result)) >= 1


def test_receipt_creation_private_no_overwrite(preflight, tmp_path):
    path, _ = preflight
    report = evaluate(path)
    target = tmp_path / "out.json"
    VERIFY.write_receipt(target, report)
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(target.read_text()) == report
    with pytest.raises(FileExistsError):
        VERIFY.write_receipt(target, report)


def test_real_cli_without_vm_preflight_fails_closed(tmp_path):
    proc = subprocess.run(["python3", str(SCRIPT),
                           "--expected-commit", SHA,
                           "--preflight-receipt", str(tmp_path / "missing.json")],
                          capture_output=True, text=True, timeout=40)
    assert proc.returncode == 2
    result = json.loads(proc.stdout)
    assert not result["host_acceptance_ready_for_operator_review_only"]
    assert not result["production_release_authorized"]
    assert "PRIVATE" not in proc.stdout


def test_untrusted_receipt_parent_directory_denied(preflight):
    path, _ = preflight
    path.parent.chmod(0o777)
    result = evaluate(path)
    assert "fresh_dedicated_worker_preflight_13_of_13" in failures(result)

