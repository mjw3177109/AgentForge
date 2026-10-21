#!/usr/bin/env python3
"""V2.5 read-only host file/identity gate for dedicated Worker staging.

Only stat/lstat and pwd lookups. Never opens or parses credentials.
Passes no raw paths, usernames, file contents or provider credentials into
the emitted receipt. This does not verify running systemd or live TLS.
"""
import argparse
import json
import os
import pwd
import stat
import sys
from pathlib import Path


def _kind(path, *, directory, root_uid, forbid_symlink=True, executable=False):
    try:
        p = Path(path)
        value = p.lstat()
        if forbid_symlink and stat.S_ISLNK(value.st_mode):
            return False
        if directory:
            if not stat.S_ISDIR(value.st_mode):
                return False
        elif not stat.S_ISREG(value.st_mode):
            return False
        if value.st_uid != root_uid or value.st_mode & 0o022:
            return False
        if not directory and executable and not value.st_mode & 0o111:
            return False
        return True
    except (OSError, ValueError):
        return False


def check_host(*, repo, python, secrets, expected_root_uid=0,
               user="agentforge", account_lookup=pwd.getpwnam):
    checks = []
    def record(name, ok, code):
        checks.append({
            "check": name, "passed": ok is True,
            "failure_code": None if ok is True else code,
        })

    try:
        entry = account_lookup(user)
        uid_ok = entry.pw_uid > 0 and entry.pw_name == user
    except (KeyError, OSError, AttributeError):
        uid_ok = False
    record("worker_unprivileged_account", uid_ok, "WORKER_ACCOUNT_MISSING_OR_ROOT")

    repo = Path(repo)
    record("trusted_repo_directory",
           _kind(repo, directory=True, root_uid=expected_root_uid)
           and _kind(repo.parent, directory=True, root_uid=expected_root_uid),
           "REPOSITORY_OWNER_OR_PERMISSIONS_UNTRUSTED")
    record("trusted_worker_source",
           _kind(repo / "src", directory=True, root_uid=expected_root_uid)
           and _kind(repo / "examples/django_host/manage.py",
                     directory=False, root_uid=expected_root_uid),
           "WORKER_SOURCE_NOT_IMMUTABLE")
    # In a normal venv bin/python is often a symlink to a trusted system
    # Python. Permit that only if the symlink itself is in a trusted venv bin
    # directory and the final executable is root-owned and not writable.
    python = Path(python)
    try:
        resolved = python.resolve(strict=True)
        link_safe = python.is_symlink() or python.is_file()
    except (OSError, RuntimeError):
        resolved = None
        link_safe = False
    py_ok = (
        link_safe and resolved is not None
        and _kind(python.parent, directory=True, root_uid=expected_root_uid)
        and _kind(resolved, directory=False, root_uid=expected_root_uid,
                  executable=True)
    )
    record("trusted_venv_python", py_ok, "VENV_PYTHON_OWNER_OR_PERMISSIONS_UNTRUSTED")

    try:
        env = Path(secrets)
        mode = env.lstat()
        safe_env = (
            stat.S_ISREG(mode.st_mode) and not stat.S_ISLNK(mode.st_mode)
            and mode.st_uid == expected_root_uid
            and stat.S_IMODE(mode.st_mode) == 0o600
            and mode.st_nlink == 1
            and _kind(env.parent, directory=True, root_uid=expected_root_uid)
        )
    except (OSError, ValueError):
        safe_env = False
    record("root_owned_0600_secret_file", safe_env,
           "SECRET_FILE_OWNER_OR_PERMISSIONS_UNSAFE")
    return {
        "schema": "agentforge.django.v25.host-prerequisites.v1",
        "ready_for_unit_staging_only": all(x["passed"] for x in checks),
        "checks_total": len(checks),
        "checks_passed": sum(x["passed"] for x in checks),
        "checks": checks,
        "secrets_read": False,
        "external_vm_identity_attested": False,
        "systemd_runtime_attested": False,
        "remote_postgres_verified": False,
        "paid_model_calls": 0,
        "production_release_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/opt/agentforge/AgentForge")
    parser.add_argument("--python", default="/opt/agentforge/venv/bin/python")
    parser.add_argument("--secrets", default="/etc/agentforge/v07-worker.env")
    args = parser.parse_args()
    report = check_host(repo=args.repo, python=args.python, secrets=args.secrets)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready_for_unit_staging_only"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
