from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agentforge.autonomous import AutonomousDevelopmentPipeline, GitHubPullRequestPublisher
from agentforge.execution_profiles import load_execution_profiles
from agentforge.live import LivePlanningPipeline
from agentforge.probe import probe_model
from agentforge.runtime_config import ExternalLLMSettings


def _settings_from_env() -> ExternalLLMSettings:
    return ExternalLLMSettings.from_env()


def _client_from_env():
    return _settings_from_env().client()


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentforge")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Generate REQ/ADR/TASK plan through a live OpenAI-compatible model")
    plan.add_argument("request")
    plan.add_argument("--req-id", default="REQ-900001")
    plan.add_argument("--adr-id", default="ADR-900001")

    sub.add_parser("model-check", help="Call the configured external model and validate strict structured JSON output")

    live = sub.add_parser("autonomous-live", help="Run the autonomous request-to-PR pipeline with an external model")
    live.add_argument("request")
    live.add_argument("--repo-root", default=".")
    live.add_argument("--profiles", default=".agent/execution-profiles.yaml")
    live.add_argument("--base", default="main")
    live.add_argument("--req-id", default="REQ-980001")
    live.add_argument("--adr-id", default="ADR-980001")
    live.add_argument("--feature-branch")
    live.add_argument("--remote", default="origin")
    live.add_argument("--push", action="store_true")
    live.add_argument("--create-pr", action="store_true")
    live.add_argument("--v3-safe-repair", action="store_true",
                      help="Enable opt-in P2 rollback and independent compile gates")
    live.add_argument("--github-repo", default=os.getenv("GITHUB_REPOSITORY", ""))

    args = parser.parse_args()

    if args.command == "plan":
        result = LivePlanningPipeline(_client_from_env()).plan(args.request, args.req_id, args.adr_id)
        _print_json({
            "requirement": result.requirement.model_dump(),
            "architecture": result.architecture.model_dump(),
            "tasks": result.tasks.model_dump()["tasks"],
        })
        return

    if args.command == "model-check":
        settings = _settings_from_env()
        result = probe_model(settings.client())
        _print_json({"settings": settings.safe_summary(), "probe": result.model_dump()})
        return

    if args.command == "autonomous-live":
        root = Path(args.repo_root).resolve()
        loaded = load_execution_profiles(root / args.profiles)
        publisher = None
        if args.create_pr:
            token = os.getenv("AGENTFORGE_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or ""
            if not token:
                raise SystemExit("--create-pr requires AGENTFORGE_GITHUB_TOKEN or GITHUB_TOKEN")
            if not args.github_repo:
                raise SystemExit("--create-pr requires --github-repo or GITHUB_REPOSITORY")
            publisher = GitHubPullRequestPublisher(args.github_repo, token)

        result = AutonomousDevelopmentPipeline(
            client=_client_from_env(),
            repo_root=root,
            profiles=loaded.profiles,
            allowed_verification_executables=loaded.allowed_executables,
            enable_v3_safe_repair=args.v3_safe_repair,
        ).run(
            args.request,
            base_branch=args.base,
            requirement_id=args.req_id,
            adr_id=args.adr_id,
            feature_branch=args.feature_branch,
            push=args.push,
            remote=args.remote,
            publisher=publisher,
            create_pr=args.create_pr,
        )
        _print_json(result.model_dump())
        if result.status not in {"SUCCESS", "PR_READY"}:
            raise SystemExit(2)
        return


if __name__ == "__main__":
    main()
