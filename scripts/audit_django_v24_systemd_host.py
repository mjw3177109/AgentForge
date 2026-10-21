#!/usr/bin/env python3
"""V2.4 read-only audit of INSTALLED systemd configuration on a Linux VM.

Never enables/starts/restarts/stops services or accesses job/db/model data.
Output is a fixed allowlisted schema, with no systemctl raw output, hostnames,
service environment values, secrets, repository paths or journal messages.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "agentforge-worker.service": ROOT / "deploy/v07/agentforge-worker.service",
    "agentforge-worker.timer": ROOT / "deploy/v07/agentforge-worker.timer",
}
SHOW_KEYS = (
    "LoadState", "ActiveState", "UnitFileState", "FragmentPath",
    "DropInPaths", "NeedDaemonReload",
)
SAFE_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "SYSTEMD_PAGER": "cat",
}


class AuditUnverifiable(RuntimeError):
    pass


def checked_systemctl(*args):
    """Read-only systemctl. Caller must not supply any state-changing verbs."""
    if not args or args[0] not in ("cat", "show"):
        raise AuditUnverifiable("Unsupported systemctl operation")
    try:
        completed = subprocess.run(
            ["systemctl", "--no-pager", *args],
            capture_output=True, text=True,
            timeout=12, env=SAFE_ENV, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise AuditUnverifiable("SYSTEMD_READ_FAILED") from exc
    if completed.returncode != 0 or len(completed.stdout) > 131072:
        raise AuditUnverifiable("SYSTEMD_READ_FAILED")
    return completed.stdout


def parse_show(text):
    values = {}
    for line in text.splitlines():
        if "=" not in line:
            raise AuditUnverifiable("SYSTEMD_SHOW_UNEXPECTED")
        key, value = line.split("=", 1)
        if key not in SHOW_KEYS or key in values:
            raise AuditUnverifiable("SYSTEMD_SHOW_UNEXPECTED")
        values[key] = value
    if set(values) != set(SHOW_KEYS):
        raise AuditUnverifiable("SYSTEMD_SHOW_INCOMPLETE")
    return values


def check_unit(unit, systemctl=checked_systemctl):
    if unit not in EXPECTED:
        raise AuditUnverifiable("UNEXPECTED_UNIT")
    expected_path = f"/etc/systemd/system/{unit}"
    status = systemctl(
        "show", unit, *(f"--property={key}" for key in SHOW_KEYS)
    )
    props = parse_show(status)
    failures = []
    if props["LoadState"] != "loaded":
        failures.append("UNIT_NOT_LOADED")
    if props["FragmentPath"] != expected_path:
        failures.append("UNIT_NOT_FROM_TRUSTED_PATH")
    if props["DropInPaths"] != "":
        failures.append("DROPIN_OVERRIDE_PRESENT")
    if props["NeedDaemonReload"] != "no":
        failures.append("DAEMON_RELOAD_REQUIRED")
    if props["ActiveState"] != "inactive":
        failures.append("UNIT_ALREADY_ACTIVE_OR_UNKNOWN")
    if props["UnitFileState"] not in (
        ("disabled", "static") if unit.endswith(".service") else ("disabled",)
    ):
        failures.append("UNIT_ENABLED_OR_UNEXPECTED")
    raw = systemctl("cat", unit)
    lines = raw.splitlines()
    if (not lines or lines[0] != "# " + expected_path
            or len(lines) < 2
            or "\n".join(lines[1:]).strip() !=
               EXPECTED[unit].read_text(encoding="utf-8").strip()):
        failures.append("INSTALLED_UNIT_DIFFERS_FROM_APPROVED_TEMPLATE")
    return sorted(set(failures))


def audit(systemctl=checked_systemctl):
    failures = []
    if sys.platform != "linux" or not Path("/run/systemd/system").is_dir():
        failures.append("NO_SYSTEMD_SYSTEM_MANAGER")
    else:
        for unit in EXPECTED:
            try:
                failures.extend(check_unit(unit, systemctl=systemctl))
            except (AuditUnverifiable, OSError, UnicodeError):
                failures.append("SYSTEMD_UNIT_VERIFICATION_UNAVAILABLE")
    return {
        "schema": "agentforge.django.v24.installed-systemd-audit.v1",
        "installed_units_match_reviewed_templates": not failures,
        "failure_codes": sorted(set(failures)),
        "service_active": False if not failures else None,
        "timer_enabled": False if not failures else None,
        "safe_to_enable_timer_automatically": False,
        "worker_preflight_performed": False,
        "remote_postgres_verified": False,
        "persistent_vm_deployed_by_this_tool": False,
        "paid_model_calls": 0,
        "production_release_authorized": False,
    }


def write_receipt(path, report):
    import tempfile
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".v24-audit-", dir=str(target.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Optional redacted JSON receipt path")
    args = parser.parse_args()
    report = audit()
    write_receipt(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["installed_units_match_reviewed_templates"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
