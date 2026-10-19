"""Run independent Django checks in a disposable copy, never the original workspace."""

import shutil
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .guard import BLOCKED_SEGMENTS, BoundaryDenied, private_environment


def _ignore(directory, entries):
    return {
        entry for entry in entries
        if entry in BLOCKED_SEGMENTS or entry.startswith(".env")
        or (Path(directory) / entry).is_symlink()
        or entry.endswith((".pyc", ".sqlite3"))
    }


def copy_workspace(source: Path, target: Path):
    if (source / ".git").is_symlink():
        raise BoundaryDenied("Git metadata symlink forbidden")
    shutil.copytree(source, target, symlinks=False, ignore=_ignore)
    return target


def run_django_checks(root: Path, with_tests=True, timeout=180):
    manage = root / "manage.py"
    if not manage.is_file() or manage.is_symlink():
        raise BoundaryDenied("manage.py missing or unsafe; no Django execution")
    checks = [
        [sys.executable, "manage.py", "check", "--no-color"],
    ]
    if with_tests:
        checks.append([sys.executable, "manage.py", "test", "--noinput", "--no-color"])
    evidence = []
    for argv in checks:
        try:
            completed = subprocess.run(
                argv, cwd=root, shell=False, env=private_environment(),
                capture_output=True, text=True, timeout=timeout,
            )
            item = {
                "argv": ["python", *argv[1:]],
                "returncode": completed.returncode,
                "stdout": completed.stdout[-5000:],
                "stderr": completed.stderr[-5000:],
                "success": completed.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            item = {"argv": ["python", *argv[1:]], "success": False,
                    "reason": "TIMEOUT", "timeout_seconds": timeout}
        # Django's test command exits successfully even when it discovers ZERO tests.
        # Never present that as independently proven business correctness.
        if with_tests and "test" in argv and item["success"]:
            output = item.get("stdout", "") + "\n" + item.get("stderr", "")
            if re.search(r"\b(?:Ran|Found) 0 tests?\b", output):
                item["success"] = False
                item["reason"] = "NO_BUSINESS_TESTS"
        evidence.append(item)
        if not item["success"]:
            break
    return {"checks": evidence, "passed": len(evidence) == len(checks)
            and all(item["success"] for item in evidence),
            "business_tests_executed": with_tests}


def isolated_verification(root: Path, with_tests=True):
    with tempfile.TemporaryDirectory(prefix="agentforge-django-verify-") as temp:
        sandbox = copy_workspace(root, Path(temp) / "workspace")
        return run_django_checks(sandbox, with_tests=with_tests)
