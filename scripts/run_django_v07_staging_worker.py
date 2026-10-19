#!/usr/bin/env python3
"""Strict CI-only scripted broker; NEVER a customer or paid-DeepSeek worker."""
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "django_host"))
sys.path.insert(0, str(ROOT))
if (
    os.getenv("CI", "").lower() != "true"
    or os.getenv("AGENTFORGE_V07_STAGING_ENABLE") != "GITHUB_ACTIONS_SYNTHETIC"
    or os.getenv("AGENTFORGE_WORKER_ROLE") != "trusted-dedicated"
    or os.getenv("DJANGO_SETTINGS_MODULE") != "config.v07_staging_worker_settings"
    or "AGENTFORGE_LLM_API_KEY" in os.environ
    or len(sys.argv) != 2
):
    raise SystemExit("BLOCKED: staging scripted worker guard")
job_id = uuid.UUID(sys.argv[1])
import django
django.setup()

from agentforge_django.audit import verify_chain
from agentforge_django.models import AgentJob
from agentforge_django.runner import run_job
from agentforge_django.v06_fixture import FakeRepairModel

fake = FakeRepairModel()
with patch("agentforge_django.v05_broker.create_v05_broker", return_value=fake) as factory:
    result = run_job(job_id)
result.refresh_from_db()
summary = {
    "type": "SYNTHETIC_BROKER_REAL_DOCKER_SEPARATE_PROCESS",
    "status": result.status,
    "role_calls": fake.calls,
    "broker_factory_calls": factory.call_count,
    "repair_attempts": result.result.get("repair_attempts"),
    "docker_rounds": result.result.get("budget", {}).get("docker_verification_rounds"),
    "audit_chain_valid": verify_chain(result),
    "candidate_only": result.result.get("production_release_authorized") is False,
}
print(json.dumps(summary))
if not (
    result.status == AgentJob.Status.PROPOSED
    and fake.calls == 5
    and factory.call_count == 1
    and summary["repair_attempts"] == 1
    and summary["docker_rounds"] == 2
    and summary["audit_chain_valid"]
    and summary["candidate_only"]
):
    raise SystemExit(2)
