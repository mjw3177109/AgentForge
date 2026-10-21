"""V2.4 verifies REAL installed systemd unit contracts without starting anything."""
import importlib.util
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_django_v24_systemd_host.py"
SPEC = importlib.util.spec_from_file_location("agentforge_v24_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def expected_systemctl(unit, *, properties=None, content=None):
    def fake(*args):
        assert args[0] in ("show", "cat"), "No changes permitted"
        assert args[1] in AUDIT.EXPECTED
        unit_name = args[1]
        if args[0] == "cat":
            if content is not None:
                return content
            return (
                f"# /etc/systemd/system/{unit_name}\n"
                + AUDIT.EXPECTED[unit_name].read_text(encoding="utf-8")
            )
        state = {
            "LoadState": "loaded",
            "ActiveState": "inactive",
            "UnitFileState": (
                "static" if unit_name.endswith(".service") else "disabled"
            ),
            "FragmentPath": f"/etc/systemd/system/{unit_name}",
            "DropInPaths": "",
            "NeedDaemonReload": "no",
        }
        state.update(properties or {})
        return "".join(f"{key}={value}\n" for key, value in state.items())
    return fake


def test_approved_service_and_timer_staged_but_disabled():
    for unit in AUDIT.EXPECTED:
        assert AUDIT.check_unit(unit, systemctl=expected_systemctl(unit)) == []


@pytest.mark.parametrize("change, reason", [
    ({"ActiveState": "active"}, "UNIT_ALREADY_ACTIVE_OR_UNKNOWN"),
    ({"DropInPaths": "/etc/systemd/system/foo.d/x.conf"}, "DROPIN_OVERRIDE_PRESENT"),
    ({"NeedDaemonReload": "yes"}, "DAEMON_RELOAD_REQUIRED"),
    ({"FragmentPath": "/usr/lib/systemd/system/foo"}, "UNIT_NOT_FROM_TRUSTED_PATH"),
    ({"LoadState": "not-found"}, "UNIT_NOT_LOADED"),
    ({"UnitFileState": "enabled"}, "UNIT_ENABLED_OR_UNEXPECTED"),
])
def test_live_systemd_override_state_not_accepted(change, reason):
    unit = "agentforge-worker.service"
    assert reason in AUDIT.check_unit(
        unit, systemctl=expected_systemctl(unit, properties=change)
    )


def test_timer_must_never_be_enabled_by_staging():
    unit = "agentforge-worker.timer"
    assert "UNIT_ENABLED_OR_UNEXPECTED" in AUDIT.check_unit(
        unit, systemctl=expected_systemctl(
            unit, properties={"UnitFileState": "enabled"}
        ),
    )


def test_installed_file_changes_detected_even_when_static_template_is_safe():
    unit = "agentforge-worker.service"
    baseline = expected_systemctl(unit)("cat", unit)
    edited = baseline.replace(
        "process_agentforge_supervised_queue", "process_agentforge_queue"
    )
    assert "INSTALLED_UNIT_DIFFERS_FROM_APPROVED_TEMPLATE" in AUDIT.check_unit(
        unit, systemctl=expected_systemctl(unit, content=edited)
    )


def test_unit_cat_extra_dropin_rejected_even_if_underlying_template_matches():
    unit = "agentforge-worker.service"
    baseline = expected_systemctl(unit)("cat", unit)
    injected = baseline + (
        "\n# /etc/systemd/system/agentforge-worker.service.d/override.conf\n"
        "[Service]\nRestart=always\n"
    )
    assert "INSTALLED_UNIT_DIFFERS_FROM_APPROVED_TEMPLATE" in AUDIT.check_unit(
        unit, systemctl=expected_systemctl(unit, content=injected)
    )


def test_partial_or_duplicate_systemctl_properties_are_not_trusted():
    unit = "agentforge-worker.timer"
    ok = expected_systemctl(unit)("show", unit)
    with pytest.raises(AUDIT.AuditUnverifiable):
        AUDIT.parse_show(ok.replace("NeedDaemonReload=no\n", ""))
    with pytest.raises(AUDIT.AuditUnverifiable):
        AUDIT.parse_show(ok + "ActiveState=active\n")


def test_audit_does_not_claim_a_deployed_vm_or_timer_permission(monkeypatch):
    monkeypatch.setattr(AUDIT.sys, "platform", "linux")
    original = Path.is_dir
    monkeypatch.setattr(
        Path, "is_dir",
        lambda path: True if str(path) == "/run/systemd/system" else original(path),
    )
    result = AUDIT.audit(systemctl=expected_systemctl("agentforge-worker.timer"))
    assert result["installed_units_match_reviewed_templates"] is True
    assert result["safe_to_enable_timer_automatically"] is False
    assert result["worker_preflight_performed"] is False
    assert result["remote_postgres_verified"] is False
    assert result["paid_model_calls"] == 0
    assert result["persistent_vm_deployed_by_this_tool"] is False


def test_audit_does_not_call_unapproved_systemctl_actions():
    with pytest.raises(AUDIT.AuditUnverifiable):
        AUDIT.checked_systemctl("start", "agentforge-worker.service")


def test_stager_is_opt_in_never_starts_timer():
    script = ROOT / "deploy/v24/stage_units.sh"
    subprocess.run(["bash", "-n", str(script)], check=True, timeout=10)
    help_result = subprocess.run(
        ["bash", str(script), "--help"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    assert "never enables/starts" in help_result.stdout
    invalid = subprocess.run(
        ["bash", str(script)],
        capture_output=True, text=True, timeout=10,
    )
    assert invalid.returncode != 0
    text = script.read_text(encoding="utf-8")
    assert "systemctl start " not in text
    assert "systemctl enable " not in text
    assert "daemon-reload" in text
    assert "--stage-reviewed-units" in text
