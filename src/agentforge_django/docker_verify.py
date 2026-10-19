"""Docker verification gate: disposable code copy and no network or inherited secrets.

Docker is NOT a hardened boundary for actively malicious code. Use a dedicated
least-privileged Linux worker, preferably nested in a VM, with no prod credentials.
"""
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from django.conf import settings

from .guard import BoundaryDenied
from .verification import copy_workspace, summarize_check


_IMAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,199}$")


def docker_image():
    image = getattr(settings, "AGENTFORGE_DOCKER_VERIFY_IMAGE", "agentforge-django-verify:0.4")
    if not isinstance(image, str) or not _IMAGE_PATTERN.fullmatch(image):
        raise BoundaryDenied("Docker verification image has unsafe syntax")
    if image.lower() in ("latest", "docker:latest") or image.endswith(":latest"):
        raise BoundaryDenied("Floating latest images are not allowed for verification")
    return image


def _run_docker(argv, *, timeout):
    return subprocess.run(
        ["docker", *argv], shell=False, capture_output=True, text=True, timeout=timeout,
        env={"PATH": __import__("os").environ.get("PATH", "")},
    )


def build_docker_command(*, image, source, name, check, memory="768m", cpus="1.0"):
    """No host project mount, Docker socket, secrets, network or privilege flags."""
    if "," in str(source) or "\n" in str(source):
        raise BoundaryDenied("Unsafe Docker bind mount source path")
    if not source.is_absolute() or not source.is_dir() or source.is_symlink():
        raise BoundaryDenied("Docker source must be an existing absolute directory")
    if check not in ("check", "test"):
        raise BoundaryDenied("Only fixed Django validation commands are permitted")
    if not re.fullmatch(r"agentforge-verify-[a-f0-9]{20}", name):
        raise BoundaryDenied("Unsafe Docker container name")
    command = [
        "run", "--rm", "--name", name, "--pull", "never",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "128",
        "--memory", memory,
        "--cpus", cpus,
        "--user", "65534:65534",
        "--workdir", "/workspace",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
        "--tmpfs", "/run:rw,noexec,nosuid,nodev,size=8m",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "HOME=/tmp",
        "--env", "PYTHONUNBUFFERED=1",
        "--mount", f"type=bind,src={source},dst=/workspace",
        image, "python", "manage.py", check, "--no-color",
    ]
    if check == "test":
        command.append("--noinput")
    return command


def docker_verification(root: Path, *, with_tests=True, timeout=180):
    """Runs a Django project in an offline container; missing Docker/image = BLOCKED."""
    if not shutil.which("docker"):
        raise BoundaryDenied("Docker CLI unavailable; refusing host subprocess fallback")
    image = docker_image()
    try:
        available = _run_docker(["image", "inspect", image], timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BoundaryDenied("Docker daemon or image preflight unavailable") from exc
    if available.returncode:
        raise BoundaryDenied("Verification Docker image not installed locally; no auto-pull")

    checks = ["check", "test"] if with_tests else ["check"]
    result = []
    with tempfile.TemporaryDirectory(prefix="agentforge-docker-work-") as tmp:
        sandbox = copy_workspace(root, Path(tmp) / "workspace")
        # Only disposable files change. The Docker process executes unprivileged;
        # allow traversal/writes in this disposable worktree alone.
        for directory in [sandbox, *sandbox.rglob("*")]:
            if directory.is_symlink():
                raise BoundaryDenied("Symlink was copied into Docker worktree")
            if directory.is_dir():
                directory.chmod(0o777)
            elif directory.is_file():
                directory.chmod(0o666)
        for check in checks:
            name = f"agentforge-verify-{uuid.uuid4().hex[:20]}"
            argv = build_docker_command(
                image=image, source=sandbox, name=name, check=check
            )
            try:
                completed = _run_docker(argv, timeout=timeout)
                item = summarize_check(
                    ["python", "manage.py", check],
                    completed.returncode,
                    completed.stdout,
                    completed.stderr,
                    is_test=check == "test",
                )
            except subprocess.TimeoutExpired:
                item = {"argv": ["python", "manage.py", check],
                        "success": False, "reason": "DOCKER_TIMEOUT"}
            except OSError:
                item = {"argv": ["python", "manage.py", check],
                        "success": False, "reason": "DOCKER_LAUNCH_ERROR"}
            finally:
                # Kill or remove an orphan if the client timed out/crashed.
                try:
                    _run_docker(["rm", "-f", name], timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            result.append(item)
            if not item["success"]:
                break
    return {
        "backend": "docker-offline",
        "checks": result,
        "passed": len(result) == len(checks) and all(x["success"] for x in result),
        "business_tests_executed": with_tests and len(result) == 2,
    }
