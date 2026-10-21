"""Independent Java/Spring transactional, exactly-once points gate.

Requires a disposable GitHub Actions runner, localhost MySQL and a fresh
schema with prefix agentforge_v41_. The generated source tree is NEVER changed:
all trusted JUnit files are installed only in an isolated, symlink-free copy.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

TRUSTED_JAVA_TEST = "TrustedPointsExactlyOnceTest.java"
GATE_NAME = "java_mysql_service_exactly_once"


def _run(argv: list[str], *, cwd: Path, env: dict, timeout: int, stdin: str | None = None):
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, input=stdin,
                                timeout=timeout, shell=False, capture_output=True, text=True)
        return {"returncode": result.returncode, "stdout": result.stdout[-8000:],
                "stderr": result.stderr[-8000:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"returncode": 124 if isinstance(e, subprocess.TimeoutExpired) else 127,
                "stdout": "", "stderr": type(e).__name__ + ": " + str(e)[:500]}


def _ensure_safe_sources(root: Path):
    for rel in ("server", "database/migrations/V980100__points.sql"):
        target = root / rel
        if target.is_symlink() or not target.exists():
            raise ValueError("MISSING_OR_SYMLINK_SOURCE:" + rel)
    for base in (root / "server", root / "database"):
        for path in base.rglob("*"):
            if path.is_symlink():
                raise ValueError("SYMLINKED_UNTRUSTED_SOURCE:" + str(path.relative_to(root)))
    if not (root / "server/pom.xml").is_file():
        raise ValueError("MISSING_MAVEN_PROJECT")


def _schema_for(run_id: str, round_index: int) -> str:
    if not re.fullmatch(r"[0-9]{1,16}", run_id):
        raise ValueError("RUN_ID_NOT_NUMERIC")
    if round_index not in (1, 2, 3):
        raise ValueError("ROUND_OUT_OF_RANGE")
    return f"agentforge_v41_{run_id}_{round_index:02d}"


def check_java_service(snapshot: Path, folder: Path, *, round_index: int,
                       run_id: str, trusted_java: Path) -> dict[str, Any]:
    blocked = {"name": GATE_NAME, "status": "FAIL", "exit_code": 2,
               "reason": "UNKNOWN", "trusted_test_executed": False}
    try:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise ValueError("GITHUB_ACTIONS_ISOLATION_REQUIRED")
        snapshot = snapshot.resolve(strict=True)
        if snapshot.is_symlink() or not snapshot.is_dir():
            raise ValueError("INVALID_SNAPSHOT")
        if trusted_java.is_symlink() or not trusted_java.is_file():
            raise ValueError("TRUSTED_JAVA_TEST_MISSING")
        if trusted_java.name != TRUSTED_JAVA_TEST:
            raise ValueError("UNTRUSTED_TEST_NAME")
        _ensure_safe_sources(snapshot)
        schema = _schema_for(run_id, round_index)
        password = os.environ.get("AGENTFORGE_V20_MYSQL_PASSWORD")
        if password is None:
            raise ValueError("ISOLATED_MYSQL_PASSWORD_MISSING")
    except (OSError, ValueError) as e:
        return {**blocked, "reason": str(e)[:600]}
    # Generated Maven code and SQL clients must never inherit the DeepSeek key,
    # GitHub runtime tokens, attestation keys, or unrelated runner secrets.
    # Only explicitly required JVM/client settings and isolated DB credentials.
    permitted = ("PATH", "HOME", "JAVA_HOME", "M2_HOME", "MAVEN_OPTS",
                 "MAVEN_CONFIG", "LANG", "LC_ALL", "TMPDIR", "TZ")
    env = {name: os.environ[name] for name in permitted if name in os.environ}
    env["AGENTFORGE_V20_MYSQL_PASSWORD"] = password
    env["MYSQL_PWD"] = password
    env["AGENTFORGE_V41_JDBC_URL"] = (
        f"jdbc:mysql://127.0.0.1:3306/{schema}?useSSL=false&serverTimezone=UTC"
    )
    mysql = ["mysql", "--protocol=TCP", "-h127.0.0.1", "-P3306", "-uroot", "-N"]
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder / "v41_java_service_gate.log"
    stages: list[dict] = []
    schema_created = False
    try:
        with tempfile.TemporaryDirectory(prefix="agentforge-v41-java-") as tmp:
            isolated = Path(tmp) / "snapshot"
            # Only copy the generated server; never modify the original repo.
            shutil.copytree(snapshot / "server", isolated / "server",
                            ignore=shutil.ignore_patterns("target", ".git", "node_modules"))
            test_dest = (isolated / "server/src/test/java/com/agentforge/shop/points" / TRUSTED_JAVA_TEST)
            test_dest.parent.mkdir(parents=True, exist_ok=True)
            if test_dest.exists() or test_dest.is_symlink():
                raise ValueError("TRUSTED_TEST_COLLISION")
            shutil.copyfile(trusted_java, test_dest)
            # Create a distinct MySQL schema, never selecting any existing DB.
            create = _run(mysql, cwd=isolated, env=env, timeout=30,
                          stdin=f"CREATE DATABASE `{schema}`;\n")
            stages.append({"step": "create", **create})
            if create["returncode"] != 0:
                raise ValueError("SCHEMA_CREATE_FAILED")
            schema_created = True
            migration = (snapshot / "database/migrations/V980100__points.sql").read_text("utf-8")
            apply = _run(mysql, cwd=isolated, env=env, timeout=90,
                         stdin=f"USE `{schema}`;\n{migration}\n")
            stages.append({"step": "migrate", **apply})
            if apply["returncode"] != 0:
                raise ValueError("SCHEMA_MIGRATION_FAILED")
            maven = _run(["mvn", "-q", "-f", "server/pom.xml",
                          "-Dtest=TrustedPointsExactlyOnceTest", "-DfailIfNoTests=true", "test"],
                         cwd=isolated, env=env, timeout=360)
            stages.append({"step": "trusted_java_maven", **maven})
            if maven["returncode"] != 0:
                raise ValueError("JAVA_SERVICE_BEHAVIOR_FAILED")
            result = {"name": GATE_NAME, "status": "PASS", "exit_code": 0,
                      "reason": "Trusted JUnit sequential/concurrent service behavior passed",
                      "trusted_test_executed": True}
    except (ValueError, OSError, shutil.Error) as e:
        result = {**blocked, "reason": str(e)[:600]}
    finally:
        if schema_created:
            cleanup = _run(mysql, cwd=folder, env=env, timeout=30,
                           stdin=f"DROP DATABASE IF EXISTS `{schema}`;\n")
            stages.append({"step": "cleanup", **cleanup})
            if cleanup["returncode"] != 0:
                result = {**blocked, "reason": "ISOLATED_SCHEMA_CLEANUP_FAILED"}
        # The log belongs to the independent runner, not the generated tree.
        with log_path.open("x", encoding="utf-8") as file:
            import json
            json.dump({"schema": schema, "stages": stages, "result": result}, file, indent=2)
            file.write("\n")
    return result
