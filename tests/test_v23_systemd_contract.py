"""V2.3 static systemd contract: no VM, service start or paid calls."""
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_django_v23_systemd.py"
SPEC = importlib.util.spec_from_file_location("agentforge_v23_systemd", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SERVICE = ROOT / "deploy/v07/agentforge-worker.service"
TIMER = ROOT / "deploy/v07/agentforge-worker.timer"


def validate_text(service, timer):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td)
        a, b = path / "service.unit", path / "timer.unit"
        a.write_text(service, encoding="utf-8")
        b.write_text(timer, encoding="utf-8")
        return MODULE.validate(a, b)


def test_versioned_service_and_timer_are_consistent():
    assert MODULE.validate(SERVICE, TIMER) == []


def test_direct_unsafe_queue_execution_is_denied():
    service = SERVICE.read_text("utf-8").replace(
        "process_agentforge_supervised_queue",
        "process_agentforge_queue",
    )
    assert "SERVICE_BOUNDED_SUPERVISION_MISSING" in validate_text(
        service, TIMER.read_text("utf-8")
    )


def test_disabling_preflight_is_denied():
    service = SERVICE.read_text("utf-8").replace(
        "check_agentforge_worker --mode dedicated --json",
        "check --deploy",
    )
    assert "SERVICE_STARTUP_PREFLIGHT_MISSING" in validate_text(
        service, TIMER.read_text("utf-8")
    )


def test_automatic_restart_and_process_group_escape_are_denied():
    service = SERVICE.read_text("utf-8").replace(
        "Restart=no", "Restart=always"
    ).replace("KillMode=control-group", "KillMode=process")
    assert "SERVICE_STOP_AND_RESTART_POLICY_UNSAFE" in validate_text(
        service, TIMER.read_text("utf-8")
    )


def test_timer_reboot_replay_change_denied():
    timer = TIMER.read_text("utf-8").replace(
        "Persistent=false", "Persistent=true"
    )
    assert "TIMER_REENTRY_OR_REBOOT_POLICY_UNSAFE" in validate_text(
        SERVICE.read_text("utf-8"), timer
    )


def test_duplicate_config_directive_cannot_override_hardened_policy():
    svc = SERVICE.read_text("utf-8") + "\n[Service]\nRestart=always\n"
    assert "UNREADABLE_OR_DUPLICATE_SYSTEMD_DIRECTIVE" in validate_text(
        svc, TIMER.read_text("utf-8")
    )


def test_missing_unit_files_fail_closed():
    assert MODULE.validate(
        "/unlikely/nonexistent/agentforge.service",
        "/unlikely/nonexistent/agentforge.timer"
    ) == ["UNREADABLE_OR_DUPLICATE_SYSTEMD_DIRECTIVE"]
