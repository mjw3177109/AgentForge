"""V2.7: scan real on-disk fixture trees; never run Worker or read secrets."""
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_django_v27_source_tree.py"
SPEC = importlib.util.spec_from_file_location("v27_source_gate", SCRIPT)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


@pytest.fixture
def project(tmp_path):
    repo = tmp_path / "AgentForge"
    for relative in GATE.REQUIRED_TREES:
        (repo / relative).mkdir(parents=True, exist_ok=True)
    for relative in GATE.REQUIRED_FILES:
        (repo / relative).write_text("project = 'test'\n", encoding="utf-8")
    module = repo / "src/agentforge_django/inner/module.py"
    module.parent.mkdir(parents=True)
    module.write_text("SENTINEL_NOT_TO_PRINT = 'secretfixture'\n", encoding="utf-8")
    return repo, module


def check(project):
    return GATE.scan_source(project, expected_root_uid=os.getuid())


def test_recursive_audit_passes_and_receipt_is_redacted(project):
    repo, _ = project
    result = check(repo)
    assert result["ready_for_unit_staging_only"]
    assert result["files_inspected"] >= 2
    assert result["directories_inspected"] >= 8
    assert result["failure_codes"] == []
    assert result["secrets_read"] is False
    assert result["source_contents_read"] is False
    assert result["production_release_authorized"] is False
    assert str(repo) not in str(result)
    assert "secretfixture" not in str(result)


def test_nested_module_group_writable_fails_closed(project):
    repo, module = project
    module.chmod(0o664)
    assert "SOURCE_ENTRY_UNTRUSTED" in check(repo)["failure_codes"]


def test_nested_directory_world_writable_fails_closed(project):
    repo, module = project
    module.parent.chmod(0o777)
    assert "SOURCE_ENTRY_UNTRUSTED" in check(repo)["failure_codes"]


def test_nested_symlink_never_followed(project, tmp_path):
    repo, module = project
    module.unlink()
    private = tmp_path / "outside"
    private.write_text("must not open", encoding="utf-8")
    module.symlink_to(private)
    assert not check(repo)["ready_for_unit_staging_only"]


def test_symlink_directory_never_followed(project, tmp_path):
    repo, _ = project
    external = tmp_path / "external"
    external.mkdir()
    (repo / "scripts").rmdir()
    (repo / "scripts").symlink_to(external, target_is_directory=True)
    assert not check(repo)["ready_for_unit_staging_only"]


def test_nonregular_named_pipe_denied(project):
    repo, module = project
    module.unlink()
    os.mkfifo(module)
    assert not check(repo)["ready_for_unit_staging_only"]


def test_missing_required_source_fails_closed(project):
    repo, _ = project
    (repo / "pyproject.toml").unlink()
    assert "SOURCE_SCAN_UNAVAILABLE" in check(repo)["failure_codes"]


def test_bounded_scan_does_not_silently_pass_partial_tree(project):
    repo, _ = project
    result = GATE.scan_source(repo, expected_root_uid=os.getuid(), max_entries=2)
    assert "SOURCE_ENTRY_LIMIT_EXCEEDED" in result["failure_codes"]
    assert result["ready_for_unit_staging_only"] is False


def test_cli_missing_vm_fails_without_source_path_leak(tmp_path):
    result = subprocess.run(
        ["python3", str(SCRIPT), "--repo", str(tmp_path / "missing")],
        check=False, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 2
    assert "SOURCE_SCAN_UNAVAILABLE" in result.stdout
    assert str(tmp_path) not in result.stdout


def test_stager_includes_gate_and_remains_never_start(project):
    text = (ROOT / "deploy/v24/stage_units.sh").read_text(encoding="utf-8")
    assert "check_django_v27_source_tree.py" in text
    assert text.index("check_django_v27_source_tree.py") < text.index("systemd-analyze verify")
    assert "systemctl start " not in text
    assert "systemctl enable " not in text
