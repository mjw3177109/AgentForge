"""Strict verification switch. Docker is default; local is a dangerous explicit opt-in."""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings

from .guard import BLOCKED_SEGMENTS, BoundaryDenied, private_environment


_SECRET_DIRS = {".ssh", ".aws", ".kube", ".config", "media", "uploads", "private"}
_SECRET_SUFFIXES = (".pem", ".p12", ".pfx", ".sqlite", ".sqlite3", ".key")


def _ignore(directory, entries):
    ignored = set()
    for entry in entries:
        lower = entry.lower()
        if (
            entry in BLOCKED_SEGMENTS or lower in _SECRET_DIRS
            or lower.startswith(".env") or lower.startswith("secret")
            or lower.endswith(_SECRET_SUFFIXES) or entry.startswith(".git")
            or (Path(directory) / entry).is_symlink()
            or lower.endswith(".pyc")
        ):
            ignored.add(entry)
    return ignored


def copy_workspace(source: Path, target: Path):
    if source.is_symlink() or not source.is_dir():
        raise BoundaryDenied("Unsafe source for disposable verification copy")
    if (source / ".git").is_symlink():
        raise BoundaryDenied("Git metadata symlink forbidden")
    shutil.copytree(source, target, symlinks=False, ignore=_ignore)
    return target


def summarize_check(argv, returncode, stdout, stderr, *, is_test):
    out = (stdout or "")[-5000:]
    err = (stderr or "")[-5000:]
    item = {
        "argv": list(argv),
        "returncode": returncode,
        "stdout": out,
        "stderr": err,
        "success": returncode == 0,
    }
    if is_test and item["success"]:
        combined = out + "\n" + err
        if not re.search(r"\bRan\s+[1-9][0-9]*\s+tests?\b", combined):
            item["success"] = False
            item["reason"] = "NO_POSITIVE_DJANGO_TEST_COUNT"
    return item


def run_django_checks(root: Path, with_tests=True, timeout=180):
    """Legacy trusted-host tests only; callers must explicitly opt in."""
    manage = root / "manage.py"
    if not manage.is_file() or manage.is_symlink():
        raise BoundaryDenied("manage.py missing or unsafe; no Django execution")
    checks = [[sys.executable, "manage.py", "check", "--no-color"]]
    if with_tests:
        checks.append([sys.executable, "manage.py", "test", "--noinput", "--no-color"])
    evidence = []
    for argv in checks:
        try:
            completed = subprocess.run(
                argv, cwd=root, shell=False, env=private_environment(),
                capture_output=True, text=True, timeout=timeout,
            )
            item = summarize_check(
                ["python", *argv[1:]], completed.returncode,
                completed.stdout, completed.stderr,
                is_test="test" in argv,
            )
        except subprocess.TimeoutExpired:
            item = {
                "argv": ["python", *argv[1:]], "success": False,
                "reason": "TIMEOUT", "timeout_seconds": timeout,
            }
        evidence.append(item)
        if not item["success"]:
            break
    return {
        "backend": "unsafe-local-dev",
        "checks": evidence,
        "passed": len(evidence) == len(checks) and all(x["success"] for x in evidence),
        "business_tests_executed": with_tests and len(evidence) == 2,
    }


def isolated_verification(root: Path, with_tests=True):
    backend = getattr(settings, "AGENTFORGE_VERIFICATION_BACKEND", "docker")
    if backend == "docker":
        from .docker_verify import docker_verification
        return docker_verification(root, with_tests=with_tests)
    if backend != "local":
        raise BoundaryDenied("Unsupported verification backend; only docker allowed by default")
    if not getattr(settings, "AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY", False):
        raise BoundaryDenied("Host verification denied; Docker must be used")
    with tempfile.TemporaryDirectory(prefix="agentforge-django-unsafe-local-") as temp:
        copy = copy_workspace(root, Path(temp) / "workspace")
        return run_django_checks(copy, with_tests=with_tests)
