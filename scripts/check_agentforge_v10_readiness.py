#!/usr/bin/env python3
"""Read-only local readiness inventory. No network request, Docker run or paid model call."""
import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def inspect(environment=None):
    env = dict(os.environ if environment is None else environment)
    model_credential_available = bool(env.get("AGENTFORGE_LLM_API_KEY"))
    approved_paid_run = (
        env.get("AGENTFORGE_V07_PAID_LIVE") == "I_APPROVE_THREE_DEEPSEEK_RUNS"
    )
    return {
        "schema": "agentforge.django.v10.readiness.v1",
        "stage": "READ_ONLY_PREFLIGHT",
        "model": {
            "credential_configured": model_credential_available,
            "explicit_paid_authorization": approved_paid_run,
            "real_deepseek_three_round_result": "NOT_RUN",
        },
        "worker": {
            "linux_posix": os.name == "posix",
            "docker_cli_present": shutil.which("docker") is not None,
            "dedicated_worker_role": env.get("AGENTFORGE_WORKER_ROLE") == "trusted-dedicated",
            "remote_vm_deployed_and_verified": False,
        },
        "production_release_authorized": False,
        "next_action": (
            "RUN_EXPLICIT_GATED_REAL_MODEL_WORKFLOW"
            if model_credential_available and approved_paid_run
            else "CONFIGURE_APPROVED_REAL_MODEL_WORKFLOW"
        ),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output")
    args = p.parse_args()
    evidence = inspect()
    evidence["inspected_at"] = datetime.now(timezone.utc).isoformat()
    contents = json.dumps(evidence, ensure_ascii=False, indent=2)
    print(contents)
    if args.output:
        dest = Path(args.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(contents + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
