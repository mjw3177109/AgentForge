"""Docker verification gate: disposable code copy and no network or inherited secrets.

Docker is NOT a hardened boundary for actively malicious code. Use a dedicated
least-privileged Linux worker, preferably nested in a VM, with no prod credentials.
"""
import hashlib
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
_IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def workspace_fingerprint(root: Path):
    """Snapshot *all* copied paths and contents, not just the Django tests.

    This detects mutation by code run during the check/test phases. It is
    defense-in-depth for the Docker read-only bind mount and is not a
    cryptographic attestation of the Docker daemon/host.
    """
    digest = hashlib.sha256()
    for entry in sorted(root.rglob("*")):
        if entry.is_symlink():
            raise BoundaryDenied("Verification worktree contains a symlink")
        rel = entry.relative_to(root).as_posix().encode("utf-8")
        if entry.is_dir():
            digest.update(b"D\0" + rel + b"\0")
        elif entry.is_file():
            digest.update(b"F\0" + rel + b"\0")
            with entry.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            raise BoundaryDenied("Unexpected non-regular verifier worktree entry")
    return digest.hexdigest()


def docker_image():
    image = getattr(settings, "AGENTFORGE_DOCKER_VERIFY_IMAGE", "agentforge-django-verify:0.4")
    if not isinstance(image, str) or not _IMAGE_PATTERN.fullmatch(image):
        raise BoundaryDenied("Docker verification image has unsafe syntax")
    if image.lower() in ("latest", "docker:latest") or image.endswith(":latest"):
        raise BoundaryDenied("Floating latest images are not allowed for verification")
    return image


def resolve_verifier_image(image):
    """Resolve the mutable label ONCE, and run both checks by content image ID.

    For a persistent Worker, the expected sha256 image ID is supplied from
    operator-controlled settings and must match the actual installed image.
    Image IDs are Docker configuration/content IDs, NOT an independently
    verified image signature or registry manifest digest.
    """
    expected = getattr(settings, "AGENTFORGE_DOCKER_VERIFY_IMAGE_ID", None)
    require_pin = getattr(settings, "AGENTFORGE_DOCKER_VERIFY_REQUIRE_PIN", False)
    if type(require_pin) is not bool:
        raise BoundaryDenied("Invalid verifier image pin enforcement switch")
    if expected is not None and (
        not isinstance(expected, str) or not _IMAGE_ID_PATTERN.fullmatch(expected)
    ):
        raise BoundaryDenied("Configured Docker image ID must be sha256 plus 64 lowercase hex")
    if require_pin and expected is None:
        raise BoundaryDenied("Production verifier requires an operator-approved image ID")
    try:
        available = _run_docker(
            ["image", "inspect", "--format", "{{.Id}}", image], timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BoundaryDenied("Docker daemon or verifier image preflight unavailable") from exc
    if available.returncode != 0:
        raise BoundaryDenied("Verification Docker image not installed locally; no auto-pull")
    actual = available.stdout.strip()
    if not _IMAGE_ID_PATTERN.fullmatch(actual):
        raise BoundaryDenied("Docker image identity missing or malformed")
    if expected is not None and actual != expected:
        raise BoundaryDenied("Installed verifier image identity differs from approved pin")
    return actual


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
        "--mount", f"type=bind,src={source},dst=/workspace,readonly",
        image, "python", "manage.py", check, "--no-color",
    ]
    if check == "test":
        command.append("--noinput")
    return command


def docker_verification(root: Path, *, with_tests=True, timeout=180):
    """Runs a Django project in an offline container; missing Docker/image = BLOCKED."""
    if not shutil.which("docker"):
        raise BoundaryDenied("Docker CLI unavailable; refusing host subprocess fallback")
    # Resolve the tag once, then execute BOTH phases using the validated
    # immutable local image ID, preventing tag-swap between check and test.
    image = resolve_verifier_image(docker_image())

    checks = ["check", "test"] if with_tests else ["check"]
    result = []
    with tempfile.TemporaryDirectory(prefix="agentforge-docker-work-") as tmp:
        sandbox = copy_workspace(root, Path(tmp) / "workspace")
        # Disposable worktree is readable by UID 65534 but never writable
        # from the Docker guest. Do not chmod 777/666; that enables writes
        # if a future Docker/mount option is accidentally weakened.
        for directory in [sandbox, *sandbox.rglob("*")]:
            if directory.is_symlink():
                raise BoundaryDenied("Symlink was copied into Docker worktree")
            if directory.is_dir():
                directory.chmod(0o755)
            elif directory.is_file():
                directory.chmod(0o644)
        original_fingerprint = workspace_fingerprint(sandbox)
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
            # Never trust a PASS if code executed by 'check' or 'test'
            # modified/created/deleted any file in the verifier source tree.
            if workspace_fingerprint(sandbox) != original_fingerprint:
                item["success"] = False
                item["reason"] = "VERIFICATION_WORKTREE_MUTATED"
            result.append(item)
            if not item["success"]:
                break
    return {
        "backend": "docker-offline",
        "verifier_image_id": image,
        "checks": result,
        "passed": len(result) == len(checks) and all(x["success"] for x in result),
        "business_tests_executed": with_tests and len(result) == 2,
    }
