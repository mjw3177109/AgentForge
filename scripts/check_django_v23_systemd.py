#!/usr/bin/env python3
"""V2.3 offline deployment contract check; does NOT install/start systemd.

Verify the tracked service and timer guardrails. This examines unit files
only; it cannot detect administrator drop-in overrides or a live VM state.
"""
import argparse
import configparser
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_unit(path):
    parser = configparser.ConfigParser(
        interpolation=None, strict=True, delimiters=("=",),
        comment_prefixes=("#", ";"), inline_comment_prefixes=None,
    )
    parser.optionxform = str
    with Path(path).open(encoding="utf-8") as stream:
        parser.read_file(stream)
    return parser


def validate(service_path, timer_path):
    failures = []
    try:
        svc = read_unit(service_path)
        timer = read_unit(timer_path)
    except (OSError, configparser.Error, UnicodeError):
        return ["UNREADABLE_OR_DUPLICATE_SYSTEMD_DIRECTIVE"]
    def need(ok, code):
        if not ok:
            failures.append(code)

    if "Service" not in svc or "Timer" not in timer:
        return ["MISSING_SYSTEMD_SERVICE_OR_TIMER_SECTION"]
    service = svc["Service"]
    tm = timer["Timer"]
    need(service.get("Type") == "oneshot", "SERVICE_MUST_BE_ONESHOT")
    need(service.get("User") == "agentforge"
         and service.get("Group") == "agentforge",
         "SERVICE_UNTRUSTED_IDENTITY")
    need(service.get("WorkingDirectory") == "/opt/agentforge/AgentForge"
         and service.get("Environment") == "DJANGO_SETTINGS_MODULE=config.v07_worker_settings"
         and service.get("EnvironmentFile") == "/etc/agentforge/v07-worker.env",
         "SERVICE_TRUSTED_SETTINGS_MISSING")
    preflight = service.get("ExecStartPre", "")
    start = service.get("ExecStart", "")
    script = "/opt/agentforge/AgentForge/examples/django_host/manage.py"
    python = "/opt/agentforge/venv/bin/python"
    need(preflight == (
        python + " " + script +
        " check_agentforge_worker --mode dedicated --json"
    ), "SERVICE_STARTUP_PREFLIGHT_MISSING")
    need(start == (
        python + " " + script +
        " process_agentforge_supervised_queue --mode dedicated"
        " --timeout-seconds 780 --include-autonomous"
    ), "SERVICE_BOUNDED_SUPERVISION_MISSING")
    try:
        timeout = int(service.get("TimeoutStartSec", ""))
    except ValueError:
        timeout = 0
    need(900 <= timeout <= 3600, "SERVICE_TIMEOUT_BOUND_INVALID")
    need(service.get("TimeoutStopSec") == "30"
         and service.get("KillMode") == "control-group"
         and service.get("SendSIGKILL") == "yes"
         and service.get("Restart") == "no",
         "SERVICE_STOP_AND_RESTART_POLICY_UNSAFE")
    need(service.get("NoNewPrivileges") == "true"
         and service.get("PrivateDevices") == "true"
         and service.get("ProtectSystem") == "full"
         and service.get("ProtectHome") == "true"
         and service.get("UMask") == "0077",
         "SERVICE_HARDENING_MISSING")
    unit = svc["Unit"] if "Unit" in svc else {}
    need("docker.service" in unit.get("Requires", "").split()
         and "docker.service" in unit.get("After", "").split(),
         "SERVICE_DOCKER_DEPENDENCY_MISSING")
    need(tm.get("Unit") == "agentforge-worker.service"
         and tm.get("Persistent") == "false"
         and tm.get("OnBootSec") == "2min"
         and tm.get("OnUnitInactiveSec") == "1min",
         "TIMER_REENTRY_OR_REBOOT_POLICY_UNSAFE")
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--service", default=str(ROOT / "deploy/v07/agentforge-worker.service")
    )
    parser.add_argument(
        "--timer", default=str(ROOT / "deploy/v07/agentforge-worker.timer")
    )
    args = parser.parse_args()
    failures = validate(args.service, args.timer)
    report = {
        "schema": "agentforge.django.v23.systemd-file-contract.v1",
        "verified": not failures,
        "failure_codes": failures,
        "static_unit_files_only": True,
        "runtime_systemd_verified": False,
        "external_vm_deployed": False,
        "real_deepseek_used": False,
        "production_release_authorized": False,
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
