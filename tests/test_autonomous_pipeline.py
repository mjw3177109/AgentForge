from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agentforge.autonomous import (
    AgentExecutionProfile,
    AutonomousDevelopmentPipeline,
    GitHubPullRequestPublisher,
)
from agentforge.coding import VerificationSpec
from agentforge.llm import OpenAICompatibleClient


class SequenceHandler(BaseHTTPRequestHandler):
    responses = []
    requests = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append({"path": self.path, "headers": dict(self.headers), "body": payload})
        content = type(self).responses.pop(0)
        body = json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GitHubHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append({"path": self.path, "headers": dict(self.headers), "body": payload})
        body = json.dumps({"html_url": "http://example.test/pr/7", "number": 7}).encode("utf-8")
        self.send_response(201)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_server(handler_cls, responses=None):
    if responses is not None:
        handler = type("Handler", (handler_cls,), {"responses": list(responses), "requests": []})
    else:
        handler = type("Handler", (handler_cls,), {"requests": []})
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


def make_git_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    run_git(repo, "config", "user.email", "agentforge@example.test")
    run_git(repo, "config", "user.name", "AgentForge CI")

    (repo / "target_tests").mkdir()
    (repo / "app").mkdir()
    (repo / "app/__init__.py").write_text("", encoding="utf-8")
    (repo / "target_tests/test_schema.py").write_text(
        "from pathlib import Path\n\n"
        "def test_schema():\n"
        "    text = Path('app/coupon_schema.txt').read_text('utf-8')\n"
        "    assert 'coupon_code' in text\n",
        encoding="utf-8",
    )
    (repo / "target_tests/test_coupon.py").write_text(
        "from app.coupon import apply_coupon\n\n"
        "def test_coupon():\n"
        "    assert apply_coupon(100) == 90\n",
        encoding="utf-8",
    )
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "initial fixture")

    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    run_git(repo, "remote", "add", "origin", str(remote))
    run_git(repo, "push", "-u", "origin", "main")
    return repo, remote


def client_for(server) -> OpenAICompatibleClient:
    host, port = server.server_address
    return OpenAICompatibleClient(
        base_url=f"http://{host}:{port}",
        api_key="test",
        model="fake-autonomous-model",
        max_attempts=1,
    )


def test_autonomous_request_to_pr_with_repair(tmp_path):
    repo, remote = make_git_repo(tmp_path)
    responses = [
        {
            "id": "REQ-900001",
            "title": "优惠券",
            "actors": ["CUSTOMER"],
            "modules": ["coupon"],
            "business_rules": ["优惠券固定减10元"],
            "acceptance": ["100元订单使用优惠券后为90元"],
            "out_of_scope": ["后台优惠券管理"],
        },
        {
            "id": "ADR-900001",
            "requirement_ids": ["REQ-900001"],
            "decision": {
                "database": {"change_required": True},
                "backend": {"change_required": True},
                "admin": {"change_required": False},
            },
            "evidence": ["REQ-900001"],
        },
        {
            "tasks": [
                {
                    "id": "TASK-900101",
                    "requirement_ids": ["REQ-900001"],
                    "adr_ids": ["ADR-900001"],
                    "assigned_agent": "database",
                    "dependencies": [],
                    "scope": {
                        "read": ["target_tests/**", "app/**"],
                        "write": ["app/**"],
                        "deny": [".agent/**"],
                    },
                    "acceptance": ["coupon schema exists"],
                    "verification": ["schema test"],
                },
                {
                    "id": "TASK-900102",
                    "requirement_ids": ["REQ-900001"],
                    "adr_ids": ["ADR-900001"],
                    "assigned_agent": "backend",
                    "dependencies": ["TASK-900101"],
                    "scope": {
                        "read": ["target_tests/**", "app/**"],
                        "write": ["app/**"],
                        "deny": [".agent/**"],
                    },
                    "acceptance": ["coupon subtracts 10"],
                    "verification": ["coupon test"],
                },
            ]
        },
        {
            "status": "SUCCESS",
            "summary": "add schema",
            "evidence": ["REQ-900001", "ADR-900001", "TASK-900101"],
            "operations": [{"op": "write_text", "path": "app/coupon_schema.txt", "content": "coupon_code varchar(64) unique\n"}],
        },
        {
            "status": "SUCCESS",
            "summary": "initial coupon implementation",
            "evidence": ["REQ-900001", "ADR-900001", "TASK-900102"],
            "operations": [{"op": "write_text", "path": "app/coupon.py", "content": "def apply_coupon(price):\n    return price + 10\n"}],
        },
        {
            "status": "SUCCESS",
            "summary": "repair coupon math",
            "evidence": ["REQ-900001", "ADR-900001", "TASK-900102"],
            "operations": [{"op": "write_text", "path": "app/coupon.py", "content": "def apply_coupon(price):\n    return price - 10\n"}],
        },
        {
            "status": "APPROVE",
            "summary": "scope and tests are correct",
            "evidence": ["REQ-900001", "ADR-900001", "TASK-900101", "TASK-900102"],
        },
    ]
    llm_server, llm_handler = start_server(SequenceHandler, responses)
    github_server, github_handler = start_server(GitHubHandler)
    try:
        py = Path(sys.executable).name
        profiles = {
            "database": AgentExecutionProfile(
                context_paths=["target_tests/test_schema.py"],
                verification=[VerificationSpec(argv=[sys.executable, "-m", "pytest", "-q", "target_tests/test_schema.py"])],
            ),
            "backend": AgentExecutionProfile(
                context_paths=["target_tests/test_coupon.py", "app/coupon_schema.txt"],
                verification=[VerificationSpec(argv=[sys.executable, "-m", "pytest", "-q", "target_tests/test_coupon.py"])],
            ),
        }
        host, port = github_server.server_address
        publisher = GitHubPullRequestPublisher(
            repo_full_name="mjw3177109/AgentForge",
            token="fake-installation-token",
            api_base=f"http://{host}:{port}",
        )
        pipeline = AutonomousDevelopmentPipeline(
            client=client_for(llm_server),
            repo_root=repo,
            profiles=profiles,
            allowed_verification_executables={py},
            max_coding_attempts=2,
        )
        result = pipeline.run(
            "给商城增加优惠券功能",
            base_branch="main",
            feature_branch="feature/REQ-900001-coupon",
            push=True,
            remote="origin",
            publisher=publisher,
            create_pr=True,
        )

        assert result.status == "PR_READY"
        assert result.pr_url == "http://example.test/pr/7"
        assert [record.task_id for record in result.task_runs] == ["TASK-900101", "TASK-900102"]
        assert result.task_runs[1].attempts == 2
        assert result.review and result.review.status == "APPROVE"
        assert "return price - 10" in (repo / "app/coupon.py").read_text("utf-8")

        assert run_git(repo, "rev-list", "--count", "main..HEAD") == "3"
        branch_ref = subprocess.run(
            ["git", "--git-dir", str(remote), "show-ref", "--verify", "refs/heads/feature/REQ-900001-coupon"],
            capture_output=True,
            text=True,
        )
        assert branch_ref.returncode == 0

        assert len(llm_handler.requests) == 7
        repair_prompt = llm_handler.requests[5]["body"]["messages"][1]["content"]
        assert "VERIFICATION FAILED" in repair_prompt
        assert "test_coupon" in repair_prompt

        assert len(github_handler.requests) == 1
        request = github_handler.requests[0]
        assert request["path"] == "/repos/mjw3177109/AgentForge/pulls"
        assert request["body"]["head"] == "feature/REQ-900001-coupon"
        assert request["body"]["base"] == "main"
        assert request["headers"]["Authorization"] == "Bearer fake-installation-token"
    finally:
        llm_server.shutdown()
        github_server.shutdown()


def test_cycle_is_rejected_before_branch_mutation(tmp_path):
    repo, _ = make_git_repo(tmp_path)
    responses = [
        {"id": "REQ-900001", "title": "cycle", "acceptance": ["x"]},
        {"id": "ADR-900001", "requirement_ids": ["REQ-900001"], "decision": {"backend": {"change_required": True}}, "evidence": ["REQ-900001"]},
        {"tasks": [
            {"id": "TASK-900101", "requirement_ids": ["REQ-900001"], "adr_ids": ["ADR-900001"], "assigned_agent": "backend", "dependencies": ["TASK-900102"], "scope": {"read": ["app/**"], "write": ["app/**"], "deny": [".agent/**"]}, "acceptance": ["x"]},
            {"id": "TASK-900102", "requirement_ids": ["REQ-900001"], "adr_ids": ["ADR-900001"], "assigned_agent": "backend", "dependencies": ["TASK-900101"], "scope": {"read": ["app/**"], "write": ["app/**"], "deny": [".agent/**"]}, "acceptance": ["x"]},
        ]},
    ]
    server, _ = start_server(SequenceHandler, responses)
    try:
        pipeline = AutonomousDevelopmentPipeline(
            client=client_for(server),
            repo_root=repo,
            profiles={"backend": AgentExecutionProfile()},
            allowed_verification_executables={Path(sys.executable).name},
        )
        try:
            pipeline.run("cycle", base_branch="main")
            assert False, "cycle should fail"
        except ValueError as exc:
            assert "cycle" in str(exc).lower()
        assert run_git(repo, "branch", "--show-current") == "main"
        assert not (repo / ".agent").exists()
    finally:
        server.shutdown()


def test_pr_requires_push(tmp_path):
    repo, _ = make_git_repo(tmp_path)
    pipeline = AutonomousDevelopmentPipeline(
        client=OpenAICompatibleClient(base_url="http://127.0.0.1:1", api_key="", model="x"),
        repo_root=repo,
        profiles={},
        allowed_verification_executables=set(),
    )
    publisher = GitHubPullRequestPublisher(
        repo_full_name="mjw3177109/AgentForge",
        token="x",
        api_base="http://127.0.0.1:1",
    )
    try:
        pipeline.run("x", push=False, create_pr=True, publisher=publisher)
        assert False, "create_pr without push should fail"
    except ValueError as exc:
        assert "push=True" in str(exc)


def test_late_discovered_task_gets_its_own_repair_budget(tmp_path):
    repo, _ = make_git_repo(tmp_path)
    responses = [
        {
            "id": "REQ-910001",
            "title": "late review repair budget",
            "actors": ["USER"],
            "modules": ["backend", "admin"],
            "business_rules": ["both tasks must converge"],
            "acceptance": ["late-discovered admin issue can still be repaired"],
            "out_of_scope": [],
        },
        {
            "id": "ADR-910001",
            "requirement_ids": ["REQ-910001"],
            "decision": {
                "backend": {"change_required": True},
                "admin": {"change_required": True},
            },
            "evidence": ["REQ-910001"],
        },
        {
            "tasks": [
                {
                    "id": "TASK-910101",
                    "requirement_ids": ["REQ-910001"],
                    "adr_ids": ["ADR-910001"],
                    "assigned_agent": "backend",
                    "dependencies": [],
                    "scope": {"read": ["app/**"], "write": ["app/**"], "deny": [".agent/**"]},
                    "acceptance": ["backend converges"],
                    "verification": [],
                },
                {
                    "id": "TASK-910102",
                    "requirement_ids": ["REQ-910001"],
                    "adr_ids": ["ADR-910001"],
                    "assigned_agent": "admin",
                    "dependencies": ["TASK-910101"],
                    "scope": {"read": ["app/**"], "write": ["app/**"], "deny": [".agent/**"]},
                    "acceptance": ["admin converges"],
                    "verification": [],
                },
            ]
        },
        {
            "status": "SUCCESS",
            "summary": "initial backend",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
            "operations": [{"op": "write_text", "path": "app/backend.txt", "content": "backend-v0\n"}],
        },
        {
            "status": "SUCCESS",
            "summary": "initial admin",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910102"],
            "operations": [{"op": "write_text", "path": "app/admin.txt", "content": "admin-raw\n"}],
        },
        {
            "status": "REQUEST_CHANGES",
            "summary": "backend issue one",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
        },
        {
            "status": "SUCCESS",
            "summary": "backend repair one",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
            "operations": [{"op": "write_text", "path": "app/backend.txt", "content": "backend-v1\n"}],
        },
        {
            "status": "REQUEST_CHANGES",
            "summary": "backend issue two",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
        },
        {
            "status": "SUCCESS",
            "summary": "backend repair two",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101"],
            "operations": [{"op": "write_text", "path": "app/backend.txt", "content": "backend-v2\n"}],
        },
        {
            "status": "REQUEST_CHANGES",
            "summary": "backend remains exhausted; admin issue discovered late",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101", "TASK-910102"],
        },
        {
            "status": "SUCCESS",
            "summary": "admin late repair",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910102"],
            "operations": [{"op": "write_text", "path": "app/admin.txt", "content": "admin-table\n"}],
        },
        {
            "status": "APPROVE",
            "summary": "late admin issue repaired; exhausted backend received no third repair",
            "evidence": ["REQ-910001", "ADR-910001", "TASK-910101", "TASK-910102"],
        },
    ]
    llm_server, llm_handler = start_server(SequenceHandler, responses)
    try:
        pipeline = AutonomousDevelopmentPipeline(
            client=client_for(llm_server),
            repo_root=repo,
            profiles={
                "backend": AgentExecutionProfile(),
                "admin": AgentExecutionProfile(),
            },
            allowed_verification_executables=set(),
            max_coding_attempts=1,
            max_review_rounds=2,
        )
        result = pipeline.run(
            "exercise per-task review repair budgets",
            base_branch="main",
            requirement_id="REQ-910001",
            adr_id="ADR-910001",
            feature_branch="feature/REQ-910001-review-budget",
        )

        assert result.status == "SUCCESS"
        assert result.review and result.review.status == "APPROVE"
        assert [record.task_id for record in result.task_runs] == [
            "TASK-910101",
            "TASK-910102",
            "TASK-910101",
            "TASK-910101",
            "TASK-910102",
        ]
        assert "backend-v2" in (repo / "app/backend.txt").read_text("utf-8")
        assert "admin-table" in (repo / "app/admin.txt").read_text("utf-8")
        assert len(llm_handler.requests) == 12
        first_review_prompt = llm_handler.requests[5]["body"]["messages"][1]["content"]
        assert "REQUEST_CHANGES has a strict burden of proof" in first_review_prompt
        assert "Do not use hypothetical or conditional concerns" in first_review_prompt
        assert "AUTHORIZED TASK WRITE SCOPES" in first_review_prompt
        assert "Tests and verification fixtures are maintainer-owned acceptance evidence" in first_review_prompt
        assert "use BLOCKED and identify the missing independent test" in first_review_prompt
        admin_repair_prompt = llm_handler.requests[10]["body"]["messages"][1]["content"]
        assert "Act only on concrete reviewer findings that explicitly apply to TASK-910102" in admin_repair_prompt
        assert "VERIFIED contracts" in admin_repair_prompt
        assert "Do not attempt to create or change tests outside this TASK's authorized write scope" in admin_repair_prompt
        assert run_git(repo, "rev-list", "--count", "main..HEAD") == "6"
    finally:
        llm_server.shutdown()


def test_reviewer_context_includes_contracts_and_declared_context(tmp_path):
    repo, _ = make_git_repo(tmp_path)
    contracts = repo / ".agent/contracts"
    contracts.mkdir(parents=True)
    (repo / ".agent/project.yaml").write_text(
        "id: PROJECT-REVIEW-CONTEXT\nverified_contracts:\n  api: .agent/contracts/API-REVIEW.yaml\n",
        encoding="utf-8",
    )
    (contracts / "API-REVIEW.yaml").write_text(
        "id: API-REVIEW\nstatus: VERIFIED\npath: /api/verified\n",
        encoding="utf-8",
    )
    (repo / "app/reviewer-context.txt").write_text(
        "AUTH_MODE=verified-existing-session\n",
        encoding="utf-8",
    )

    pipeline = AutonomousDevelopmentPipeline(
        client=OpenAICompatibleClient(base_url="http://127.0.0.1:1", api_key="", model="x"),
        repo_root=repo,
        profiles={
            "backend": AgentExecutionProfile(context_paths=["app/reviewer-context.txt"]),
        },
        allowed_verification_executables=set(),
    )
    context = pipeline._review_context()

    assert "--- .agent/project.yaml ---" in context
    assert "--- .agent/contracts/API-REVIEW.yaml ---" in context
    assert "path: /api/verified" in context
    assert "--- app/reviewer-context.txt ---" in context
    assert "AUTH_MODE=verified-existing-session" in context

