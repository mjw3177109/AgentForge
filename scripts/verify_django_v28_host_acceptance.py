#!/usr/bin/env python3
"""V2.8 fail-closed read-only host acceptance receipt aggregator.

Operator supplies a fresh dedicated-worker preflight JSON captured separately
under the systemd EnvironmentFile on the reviewed VM. This script verifies
local Git revision, host/source/systemd gates, and the receipt schema without
starting a Worker, reading provider credentials, or running Django itself.
It does not attest the VM's identity or authorize production release.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_PRECHECK_BYTES = 65536
MAX_SUBPROCESS_BYTES = 65536
RECEIPT_MAX_AGE = 300
SAFE_ENV = {
    "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
    "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
}
CHECK_NAMES = (
    "execution_mode", "dedicated_role", "unsafe_execution_disabled",
    "postgresql_with_heartbeat", "postgres_transport", "project_roots",
    "model_secret_gate", "pinned_verifier_config", "postgres_readonly_query",
    "schema_migrations_applied", "no_prior_worker_leases",
    "docker_verifier_identity", "orphan_verifier_containers",
)


class ReceiptRejected(Exception):
    pass


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptRejected("Duplicate JSON key")
        result[key] = value
    return result


def _read_preflight(path, *, now=None, expected_uid=0,
                    _fixture_ancestry_boundary=None):
    """Root-owned, short-lived, non-symlink evidence; no raw data returned."""
    fd = None
    try:
        target = Path(path)
        if not target.is_absolute() or ".." in target.parts:
            raise ReceiptRejected("Unsafe preflight pathname")
        # No mutable or symlinked parent directory may replace a receipt.
        ancestors = (target.parent, *target.parent.parents)
        if _fixture_ancestry_boundary is not None:
            # Explicit unit-test fixture only. Never exposed in production CLI.
            boundary = Path(_fixture_ancestry_boundary)
            if boundary not in ancestors:
                raise ReceiptRejected("Unsafe fixture boundary")
            ancestors = ancestors[:ancestors.index(boundary) + 1]
        for directory in ancestors:
            parent_info = directory.lstat()
            if (not stat.S_ISDIR(parent_info.st_mode)
                    or parent_info.st_uid != expected_uid
                    or parent_info.st_mode & 0o022):
                raise ReceiptRejected("Untrusted receipt directory")
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or not 1 <= info.st_size <= MAX_PRECHECK_BYTES):
            raise ReceiptRejected("Untrusted preflight file")
        t = time.time() if now is None else now
        if not 0 <= t - info.st_mtime <= RECEIPT_MAX_AGE:
            raise ReceiptRejected("Expired or future-dated preflight")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened = os.fstat(fd)
        if ((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) !=
                (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)):
            raise ReceiptRejected("Preflight changed during inspection")
        # Read through the validated descriptor, not through a pathname race.
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(MAX_PRECHECK_BYTES + 1)
        if len(raw) > MAX_PRECHECK_BYTES:
            raise ReceiptRejected("Preflight exceeds byte limit")
        report = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object)
        if not isinstance(report, dict):
            raise ReceiptRejected("Invalid report structure")
        return report, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptRejected("Preflight unreadable") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _valid_preflight(report):
    if not isinstance(report, dict):
        return False
    if (report.get("schema") != "agentforge.django.v23.worker-preflight.v1"
            or report.get("mode") != "dedicated"
            or report.get("ready_to_accept_candidate_only_jobs") is not True
            or report.get("external_vm_independently_attested") is not False
            or report.get("real_deepseek_tested") is not False
            or report.get("production_release_authorized") is not False):
        return False
    checks = report.get("checks")
    if not isinstance(checks, list) or len(checks) != len(CHECK_NAMES):
        return False
    if [item.get("check") for item in checks if isinstance(item, dict)] != list(CHECK_NAMES):
        return False
    if any(item.get("passed") is not True or item.get("failure_code") is not None
           for item in checks):
        return False
    return (type(report.get("checks_total")) is int
            and type(report.get("checks_passed")) is int
            and report["checks_total"] == len(CHECK_NAMES)
            and report["checks_passed"] == len(CHECK_NAMES))


def _invoke(args, runner, *, timeout=40):
    try:
        proc = runner(args, capture_output=True, text=True, timeout=timeout,
                      check=False, env=SAFE_ENV)
        if proc.returncode != 0 or len(proc.stdout) > MAX_SUBPROCESS_BYTES:
            return None
        return proc.stdout
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError):
        return None


def _gate_json(script, success_key, schema, runner, repo):
    output = _invoke([sys.executable, str(repo / "scripts" / script)], runner)
    if output is None:
        return False
    try:
        result = json.loads(output, object_pairs_hook=_json_object)
        return (isinstance(result, dict) and result.get("schema") == schema
                and result.get(success_key) is True
                and result.get("production_release_authorized") is False)
    except (ValueError, UnicodeError, ReceiptRejected):
        return False


def evaluate(*, preflight_path, expected_commit, repo=ROOT,
             runner=subprocess.run, expected_uid=0, now=None,
             _fixture_ancestry_boundary=None):
    """No subprocess writes. Preflight is evidence, not executed here."""
    checks = []
    digest = None

    def record(name, passed, code):
        checks.append({"check": name, "passed": passed is True,
                       "failure_code": None if passed is True else code})

    valid_sha = isinstance(expected_commit, str) and bool(re.fullmatch(
        r"[0-9a-f]{40}", expected_commit))
    revision = None
    if valid_sha:
        revision = _invoke(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"], runner)
    record("pinned_git_revision", bool(revision and revision.strip() == expected_commit),
           "GIT_REVISION_UNVERIFIED_OR_MISMATCH")
    dirty = None
    if checks[-1]["passed"]:
        dirty = _invoke(["git", "-C", str(repo), "status", "--porcelain=v1",
                         "--untracked-files=all", "--", "src", "scripts",
                         "examples/django_host", "deploy", "pyproject.toml"], runner)
    record("clean_worker_worktree", dirty == "" if dirty is not None else False,
           "WORKTREE_DIRTY_OR_UNVERIFIED")

    record("trusted_host_prerequisites", _gate_json(
        "check_django_v25_host.py", "ready_for_unit_staging_only",
        "agentforge.django.v25.host-prerequisites.v1", runner, repo),
        "HOST_PREREQUISITES_REJECTED")
    record("trusted_recursive_source_tree", _gate_json(
        "check_django_v27_source_tree.py", "ready_for_unit_staging_only",
        "agentforge.django.v27.source-tree-gate.v1", runner, repo),
        "SOURCE_TREE_REJECTED")
    record("staged_systemd_units_disabled", _gate_json(
        "audit_django_v24_systemd_host.py", "installed_units_match_reviewed_templates",
        "agentforge.django.v24.installed-systemd-audit.v1", runner, repo),
        "SYSTEMD_STATE_REJECTED")

    try:
        preflight, digest = _read_preflight(
            preflight_path, now=now, expected_uid=expected_uid,
            _fixture_ancestry_boundary=_fixture_ancestry_boundary)
        trusted_preflight = _valid_preflight(preflight)
    except ReceiptRejected:
        trusted_preflight = False
    record("fresh_dedicated_worker_preflight_13_of_13", trusted_preflight,
           "DEDICATED_PREFLIGHT_MISSING_EXPIRED_OR_REJECTED")

    return {
        "schema": "agentforge.django.v28.host-acceptance.v1",
        "host_acceptance_ready_for_operator_review_only": all(c["passed"] for c in checks),
        "checks_total": len(checks),
        "checks_passed": sum(c["passed"] for c in checks),
        "checks": checks,
        "expected_commit": expected_commit if valid_sha else None,
        "preflight_sha256": digest,
        "preflight_freshness_seconds_max": RECEIPT_MAX_AGE,
        "preflight_executed_by_this_tool": False,
        "source_contents_read": False,
        "model_credentials_read": False,
        "external_vm_identity_attested": False,
        "remote_postgres_directly_probed_by_this_tool": False,
        "worker_started_or_enabled": False,
        "paid_model_calls": 0,
        "production_release_authorized": False,
    }


def write_receipt(path, report):
    """Create new private artifact, never overwrite an existing receipt."""
    if path is None:
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = None
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd is not None:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-receipt", required=True)
    parser.add_argument("--expected-commit", required=True,
                        help="40-character reviewed git SHA, obtained out of band")
    parser.add_argument("--output", help="Path to NEW private JSON receipt (never overwritten)")
    args = parser.parse_args()
    result = evaluate(preflight_path=args.preflight_receipt,
                      expected_commit=args.expected_commit)
    try:
        write_receipt(args.output, result)
    except OSError:
        # No path or exception content; avoid private host details in CI logs.
        print(json.dumps({"schema": result["schema"],
                          "failure_code": "RECEIPT_OUTPUT_UNAVAILABLE",
                          "production_release_authorized": False}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["host_acceptance_ready_for_operator_review_only"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
