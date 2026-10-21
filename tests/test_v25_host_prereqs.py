"""V2.5 host preflight: only file metadata, never read secrets."""
import importlib.util
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v25_host_prereqs", ROOT / "scripts/check_django_v25_host.py"
)
HOST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOST)


@pytest.fixture
def vm(tmp_path):
    repo = tmp_path / "AgentForge"
    (repo / "src").mkdir(parents=True)
    manager = repo / "examples/django_host/manage.py"
    manager.parent.mkdir(parents=True)
    manager.write_text("print('fixture-only')", encoding="utf-8")
    env = tmp_path / "etc" / "v07-worker.env"
    env.parent.mkdir()
    env.write_text(
        "AGENTFORGE_LLM_API_KEY=VERY_PRIVATE_FIXTURE_SECRET\n", encoding="utf-8"
    )
    env.chmod(0o600)
    python = tmp_path / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    user = lambda _: SimpleNamespace(pw_uid=2001, pw_name="agentforge")
    def check():
        return HOST.check_host(
            repo=repo, python=python, secrets=env,
            expected_root_uid=os.getuid(), account_lookup=user
        )
    return repo, manager, env, python, check


def codes(report):
    return {x["check"]: x["failure_code"] for x in report["checks"]}


def test_safe_readonly_metadata_preflight_emits_no_paths_or_secrets(vm):
    _, _, _, _, check = vm
    result = check()
    assert result["ready_for_unit_staging_only"] is True
    assert result["checks_total"] == result["checks_passed"] == 5
    assert result["secrets_read"] is False
    assert result["production_release_authorized"] is False
    assert "PRIVATE" not in str(result)
    assert "/tmp/" not in str(result)


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o666, 0o400])
def test_env_secrets_must_be_root_owned_0600(vm, mode):
    _, _, env, _, check = vm
    env.chmod(mode)
    assert codes(check())["root_owned_0600_secret_file"] == (
        "SECRET_FILE_OWNER_OR_PERMISSIONS_UNSAFE"
    )


def test_symlink_to_secret_file_denied(vm):
    _, _, env, _, check = vm
    real = env.with_name("real.env")
    env.rename(real)
    env.symlink_to(real)
    assert check()["ready_for_unit_staging_only"] is False


def test_repo_parent_and_source_require_immutable_permissions(vm):
    repo, manager, _, _, check = vm
    repo.chmod(0o777)
    assert codes(check())["trusted_repo_directory"] == (
        "REPOSITORY_OWNER_OR_PERMISSIONS_UNTRUSTED"
    )
    repo.chmod(0o755)
    manager.chmod(0o666)
    assert codes(check())["trusted_worker_source"] == (
        "WORKER_SOURCE_NOT_IMMUTABLE"
    )


def test_bad_venv_python_is_denied(vm):
    _, _, _, py, check = vm
    py.chmod(0o777)
    assert codes(check())["trusted_venv_python"] == (
        "VENV_PYTHON_OWNER_OR_PERMISSIONS_UNTRUSTED"
    )


def test_unprivileged_worker_uid_required(vm):
    _, _, _, _, check = vm
    # Substitute the actual local uid user account identity, which may be
    # root on an isolated test container. No OS user is created or changed.
    result = HOST.check_host(
        repo="/missing", python="/missing", secrets="/missing",
        account_lookup=lambda _: SimpleNamespace(pw_uid=0, pw_name="agentforge"),
    )
    assert codes(result)["worker_unprivileged_account"] == (
        "WORKER_ACCOUNT_MISSING_OR_ROOT"
    )


def test_deployment_stager_is_opt_in_and_rolls_back_exact_created_files():
    script = ROOT / "deploy/v24/stage_units.sh"
    subprocess.run(["bash", "-n", str(script)], check=True, timeout=10)
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(["bash", str(script)], check=True,
                       capture_output=True, timeout=10)
    content = script.read_text(encoding="utf-8")
    assert 'flock -n 9' in content
    assert "trap cleanup EXIT" in content
    assert 'cmp -s "$SERVICE" "$TARGET/agentforge-worker.service"' in content
    assert 'cmp -s "$TIMER" "$TARGET/agentforge-worker.timer"' in content
    assert "check_django_v25_host.py" in content
    assert "systemctl enable " not in content
    assert "systemctl start " not in content
