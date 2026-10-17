from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentforge.autonomous import (
    AgentExecutionProfile,
    AutonomousDevelopmentPipeline,
    ReviewDecision,
)
from agentforge.llm import OpenAICompatibleClient


class SequenceHandler(BaseHTTPRequestHandler):
    responses = []
    requests = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(payload)
        content = type(self).responses.pop(0)
        body = json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_server(responses):
    handler = type("Handler", (SequenceHandler,), {"responses": list(responses), "requests": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, handler


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    run_git(repo, "config", "user.email", "agentforge@example.test")
    run_git(repo, "config", "user.name", "AgentForge CI")
    (repo / "app").mkdir()
    (repo / "app/README.md").write_text("Only app/ may be changed.\n", encoding="utf-8")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "initial")
    return repo


def client_for(server) -> OpenAICompatibleClient:
    host, port = server.server_address
    return OpenAICompatibleClient(
        base_url=f"http://{host}:{port}",
        api_key="test",
        model="fake-review-repair-model",
        max_attempts=1,
    )


def test_review_decision_rejects_prose_evidence():
    with pytest.raises(ValidationError, match="evidence"):
        ReviewDecision(
            status="REQUEST_CHANGES",
            summary="fix the implementation",
            evidence=["app/value.txt is wrong"],
        )


def test_review_changes_require_routable_task_id():
    with pytest.raises(ValidationError, match="TASK"):
        ReviewDecision(
            status="REQUEST_CHANGES",
            summary="fix the implementation",
            evidence=["REQ-900001", "ADR-900001"],
        )


def test_read_only_review_routes_bounded_repair_then_reapproves(tmp_path: Path):
    repo = make_repo(tmp_path)
    responses = [
        {
            "id": "REQ-900001",
            "title": "write value",
            "actors": ["USER"],
            "modules": ["app"],
            "business_rules": ["value must be good"],
            "acceptance": ["app/value.txt contains good"],
            "out_of_scope": [],
        },
        {
            "id": "ADR-900001",
            "requirement_ids": ["REQ-900001"],
            "decision": {"app": {"change_required": True}},
            "evidence": ["REQ-900001"],
        },
        {
            "tasks": [
                {
                    "id": "TASK-900101",
                    "requirement_ids": ["REQ-900001"],
                    "adr_ids": ["ADR-900001"],
                    "assigned_agent": "app",
                    "dependencies": [],
                    "scope": {
                        "read": ["app/**"],
                        "write": ["app/"],
                        "deny": [".agent/**"],
                    },
                    "acceptance": ["value is good"],
                    "verification": [],
                }
            ]
        },
        {
            "status": "SUCCESS",
            "summary": "initial implementation",
            "evidence": ["REQ-900001", "ADR-900001", "TASK-900101"],
            "operations": [
                {"op": "write_text", "path": "app/value.txt", "content": "bad\n"}
            ],
        },
        {
            "status": "REQUEST_CHANGES",
            "summary": "TASK-900101 must replace bad with good in app/value.txt.",
            "evidence": ["REQ-900001", "ADR-900001", "TASK-900101"],
        },
        {
            "status": "SUCCESS",
            "summary": "review repair",
            "evidence": ["REQ-900001", "ADR-900001", "TASK-900101"],
            "operations": [
                {"op": "write_text", "path": "app/value.txt", "content": "good\n"}
            ],
        },
        {
            "status": "APPROVE",
            "summary": "review repair is correct",
            "evidence": ["REQ-900001", "ADR-900001", "TASK-900101"],
        },
    ]
    server, handler = start_server(responses)
    try:
        pipeline = AutonomousDevelopmentPipeline(
            client=client_for(server),
            repo_root=repo,
            profiles={
                "app": AgentExecutionProfile(
                    context_paths=["app/README.md"],
                    read_scope=["app/**"],
                    write_scope=["app/**"],
                    deny_scope=[".agent/**"],
                    verification=[],
                )
            },
            allowed_verification_executables=set(),
            max_coding_attempts=1,
            max_review_rounds=1,
        )
        result = pipeline.run(
            "write a good value",
            base_branch="main",
            feature_branch="feature/REQ-900001-review-repair",
        )

        assert result.status == "SUCCESS"
        assert result.review and result.review.status == "APPROVE"
        assert (repo / "app/value.txt").read_text(encoding="utf-8") == "good\n"
        assert run_git(repo, "rev-list", "--count", "main..HEAD") == "3"
        assert [record.task_id for record in result.task_runs] == ["TASK-900101", "TASK-900101"]
        assert result.task_runs[-1].message.startswith("review repair round 1")

        repair_prompt = handler.requests[5]["messages"][1]["content"]
        assert "READ-ONLY REVIEWER REQUESTED CHANGES" in repair_prompt
        assert "TASK-900101 must replace bad with good" in repair_prompt
        assert "FILE app/value.txt:\nbad" in repair_prompt
    finally:
        server.shutdown()
