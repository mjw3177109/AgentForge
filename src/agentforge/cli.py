from __future__ import annotations

import argparse
import json
import os

from agentforge.live import LivePlanningPipeline
from agentforge.llm import OpenAICompatibleClient


def _client_from_env() -> OpenAICompatibleClient:
    base_url = os.getenv("AGENTFORGE_LLM_BASE_URL", "").strip()
    model = os.getenv("AGENTFORGE_LLM_MODEL", "").strip()
    if not base_url or not model:
        raise SystemExit("Set AGENTFORGE_LLM_BASE_URL and AGENTFORGE_LLM_MODEL first")
    return OpenAICompatibleClient(
        base_url=base_url,
        api_key=os.getenv("AGENTFORGE_LLM_API_KEY", ""),
        model=model,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentforge")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Generate REQ/ADR/TASK plan through a live OpenAI-compatible model")
    plan.add_argument("request")
    plan.add_argument("--req-id", default="REQ-900001")
    plan.add_argument("--adr-id", default="ADR-900001")
    args = parser.parse_args()

    if args.command == "plan":
        result = LivePlanningPipeline(_client_from_env()).plan(args.request, args.req_id, args.adr_id)
        print(json.dumps({
            "requirement": result.requirement.model_dump(),
            "architecture": result.architecture.model_dump(),
            "tasks": result.tasks.model_dump()["tasks"],
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
