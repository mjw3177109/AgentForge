#!/usr/bin/env python3
"""Ephemeral PostgreSQL + actual web process + separate worker + real offline Docker.

Does not provision any persistent VM; performs a temporary integration check.
Only synthetic fixture code and a mock model are used. No DeepSeek calls.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "examples" / "django_host"
sys.path.insert(0, str(HOST))
sys.path.insert(0, str(ROOT))

if (
    os.environ.get("CI", "").lower() != "true"
    or os.environ.get("AGENTFORGE_V07_STAGING_ENABLE") != "GITHUB_ACTIONS_SYNTHETIC"
    or "AGENTFORGE_LLM_API_KEY" in os.environ
):
    raise SystemExit("BLOCKED: staging runs only in synthetic GitHub CI without LLM key")


def git(path, *args):
    process = subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True,
        timeout=20,
    )
    return process.stdout.strip()


def spawn_env(role, workspaces):
    values = os.environ.copy()
    values.pop("AGENTFORGE_LLM_API_KEY", None)
    values["AGENTFORGE_ALLOWED_ROOTS"] = str(workspaces)
    values["DJANGO_SETTINGS_MODULE"] = "config.v07_staging_" + role + "_settings"
    if role == "worker":
        values["AGENTFORGE_WORKER_ROLE"] = "trusted-dedicated"
        values["AGENTFORGE_V06_ENABLE_WORKER"] = "I_ACCEPT_DEDICATED_WORKER"
    else:
        values.pop("AGENTFORGE_WORKER_ROLE", None)
        values.pop("AGENTFORGE_V06_ENABLE_WORKER", None)
    return values


def main():
    with tempfile.TemporaryDirectory(prefix="agentforge-v07-crossprocess-") as temp:
        workspaces = Path(temp) / "workspaces"
        workspaces.mkdir()
        control = spawn_env("control", workspaces)
        worker = spawn_env("worker", workspaces)
        os.environ.update(control)
        from agentforge_django.v05_fixture import REQUEST, make_fixture
        project_root = make_fixture(workspaces / "demo")
        policy = project_root / ".agent"
        policy.mkdir()
        (policy / "execution-profiles.yaml").write_text(
            "allowed_verification_executables: []\n"
            "agents:\n  backend:\n"
            "    read_scope: [app/**]\n"
            "    write_scope: [app/**]\n"
            "    deny_scope: [.agent/**]\n", encoding="utf-8"
        )
        git(project_root, "init", "-b", "main")
        git(project_root, "config", "user.name", "Ephemeral CI")
        git(project_root, "config", "user.email", "v07@localhost.invalid")
        git(project_root, "add", ".")
        git(project_root, "commit", "-m", "synthetic fixture")
        original_sha = git(project_root, "rev-parse", "HEAD")

        import django
        django.setup()
        from django.core.management import call_command
        call_command("migrate", interactive=False, verbosity=0)
        from django.contrib.auth import get_user_model
        from agentforge_django.models import ManagedProject, AgentJob
        from agentforge_django.audit import verify_chain
        from agentforge_django.control import create_pending_job, approve_pending_job
        from agentforge_django.docker_verify import docker_verification
        from agentforge_django.v06_repair import _accepted

        baseline = docker_verification(project_root)
        if baseline.get("passed") is not False:
            raise RuntimeError("Baseline bug must be demonstrated by real Docker")

        admin = get_user_model().objects.create_superuser(
            username="v07-ephemeral", email="test@localhost.invalid",
            password="not-a-production-password"
        )
        project = ManagedProject.objects.create(
            name="staging-fixture", root_path=str(project_root),
            enabled=True, autonomous_enabled=True, run_business_tests=True,
            base_branch="main", write_scopes=["app/**"],
        )
        job = create_pending_job(
            actor=admin, project=project, mode=AgentJob.Mode.AUTONOMOUS,
            request_text=REQUEST,
        )
        approval = approve_pending_job(
            actor=admin, job_id=job.pk,
            reason="Ephemeral CI fixture only; candidate patch is not a deployment",
        )
        if approval.base_commit != original_sha:
            raise RuntimeError("Approval not pinned to original Git commit")

        # A REAL separate Django HTTP process uses only control-plane settings.
        server = subprocess.Popen(
            [sys.executable, str(HOST / "manage.py"), "runserver", "--noreload",
             "127.0.0.1:18777"],
            cwd=ROOT, env=control, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            endpoint_ready = False
            for _ in range(60):
                if server.poll() is not None:
                    raise RuntimeError("Control plane server exited prematurely")
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:18777/agentforge/", timeout=1
                    ) as response:
                        endpoint_ready = response.status == 200
                    if endpoint_ready:
                        break
                except Exception:
                    time.sleep(0.25)
            if not endpoint_ready:
                raise RuntimeError("Control plane HTTP endpoint failed")

            # Real OS subprocess: separate Django init, permissions and DB connection.
            executed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" /
                                     "run_django_v07_staging_worker.py"), str(job.pk)],
                cwd=ROOT, env=worker, capture_output=True,
                text=True, timeout=480,
            )
            if executed.returncode:
                raise RuntimeError(
                    "Staging worker failed: " + executed.stdout[-1400:] +
                    " / " + executed.stderr[-400:]
                )
            worker_evidence = json.loads(executed.stdout.strip().splitlines()[-1])
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)

        job.refresh_from_db()
        project_file_unchanged = (
            "return a - b" in (project_root / "app/views.py").read_text("utf-8")
            and git(project_root, "status", "--porcelain") == ""
            and git(project_root, "rev-parse", "HEAD") == original_sha
        )
        independent = job.result.get("independent_verification", {})
        # V0.8 human handoff: authenticated superuser receives candidate-only
        # bytes; git apply --check validates usability WITHOUT applying them.
        from django.test import Client
        from django.urls import reverse
        client = Client()
        client.force_login(admin)
        patch_response = client.get(reverse(
            "agentforge_django:download_candidate_patch", args=[job.pk]
        ))
        export_ok = (
            patch_response.status_code == 200
            and patch_response.get("X-AgentForge-Candidate-Only") == "true"
            and patch_response.get("X-AgentForge-Patch-SHA256") ==
                job.result.get("patch_sha256")
        )
        apply_check_ok = False
        if export_ok:
            check = subprocess.run(
                ["git", "apply", "--check", "-p1", "-"],
                input=patch_response.content,
                cwd=project_root, capture_output=True, timeout=15,
            )
            apply_check_ok = check.returncode == 0
        evidence = {
            "gate": "EPHEMERAL_POSTGRES_CROSS_PROCESS_REAL_DOCKER_FAKE_LLM",
            "http_control_plane_started": endpoint_ready,
            "postgres_shared_state": True,
            "independent_worker_exited": True,
            "job_status": job.status,
            "approval_commit_pinned": approval.base_commit == original_sha,
            "audit_hash_chain_valid": verify_chain(job),
            "worker": worker_evidence,
            "docker_final_pass": _accepted(independent),
            "source_repo_unchanged": project_file_unchanged,
            "candidate_download_integrity_ok": export_ok,
            "candidate_git_apply_check_only": apply_check_ok,
            "real_deepseek_tested": False,
            "persistent_remote_worker_deployed": False,
            "production_release_authorized": False,
        }
        print(json.dumps(evidence, ensure_ascii=False))
        if not (
            job.status == AgentJob.Status.PROPOSED
            and evidence["docker_final_pass"]
            and project_file_unchanged
            and evidence["audit_hash_chain_valid"]
            and export_ok and apply_check_ok
        ):
            raise SystemExit(2)


if __name__ == "__main__":
    main()
