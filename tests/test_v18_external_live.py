from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agentforge.autonomous import AgentExecutionProfile, AutonomousDevelopmentPipeline
from agentforge.coding import AgentAction, FileOperation, LiveCodingRuntime
from agentforge.contracts import RequirementDraft, TaskDraft, TaskScope
from agentforge.execution_profiles import load_execution_profiles
from agentforge.llm import OpenAICompatibleClient
from agentforge.probe import probe_model
from agentforge.runtime_config import ExternalLLMSettings


class _ProbeHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        _ = json.loads(self.rfile.read(length).decode("utf-8"))
        payload = {
            "choices": [{"message": {"content": json.dumps({"ok": True, "message": "external-model-ready"})}}]
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def _serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_external_settings_reject_plain_http_remote(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_LLM_BASE_URL", "http://example.com/v1")
    monkeypatch.setenv("AGENTFORGE_LLM_MODEL", "model-x")
    monkeypatch.setenv("AGENTFORGE_LLM_API_KEY", "secret")
    with pytest.raises(ValueError, match="HTTPS"):
        ExternalLLMSettings.from_env()


def test_external_settings_require_key_for_remote(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("AGENTFORGE_LLM_MODEL", "model-x")
    monkeypatch.delenv("AGENTFORGE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("AGENTFORGE_LLM_ALLOW_ANONYMOUS", raising=False)
    with pytest.raises(ValueError, match="API_KEY"):
        ExternalLLMSettings.from_env()


def test_external_settings_never_expose_api_key():
    settings = ExternalLLMSettings(
        base_url="https://example.com/v1",
        model="model-x",
        api_key="super-secret-token",
    )
    summary = json.dumps(settings.safe_summary())
    assert "super-secret-token" not in summary
    assert "api_key_configured" in summary


def test_loopback_model_probe_uses_real_http_transport():
    server, thread = _serve()
    try:
        settings = ExternalLLMSettings(
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            model="fake-live-model",
        )
        result = probe_model(settings.client())
        assert result.ok is True
        assert result.message == "external-model-ready"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_structured_client_includes_schema_and_repairs_validation_error(monkeypatch):
    calls: list[str] = []
    responses = iter([
        json.dumps({
            "id": "REQ-980001",
            "title": "商城积分",
            "actors": ["CUSTOMER"],
            "modules": ["backend"],
            "business_rules": ["消费可获得积分"],
            "out_of_scope": [],
        }, ensure_ascii=False),
        json.dumps({
            "id": "REQ-980001",
            "title": "商城积分",
            "actors": ["CUSTOMER"],
            "modules": ["backend"],
            "business_rules": ["消费可获得积分"],
            "acceptance": ["积分规则可以被验证"],
            "out_of_scope": [],
        }, ensure_ascii=False),
    ])

    def fake_request(self, system: str, user: str) -> str:
        calls.append(user)
        return next(responses)

    monkeypatch.setattr(OpenAICompatibleClient, "_request", fake_request)
    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:1",
        api_key="",
        model="fake",
        max_attempts=2,
    )
    result = client.complete_model(
        "system",
        "Create requirement REQ-980001",
        RequirementDraft,
    )

    assert result.id == "REQ-980001"
    assert result.acceptance == ["积分规则可以被验证"]
    assert "JSON Schema" in calls[0]
    assert '"acceptance"' in calls[0]
    assert "failed strict validation" in calls[1]
    assert "acceptance" in calls[1]


def test_execution_profiles_reject_shell(tmp_path: Path):
    path = tmp_path / "profiles.yaml"
    path.write_text(
        """
allowed_verification_executables: [bash, pytest]
agents:
  backend:
    context_paths: [server]
    verification:
      - argv: [bash, -lc, pytest]
        cwd: .
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Shell"):
        load_execution_profiles(path)


def test_execution_profiles_require_allowlisted_executable(tmp_path: Path):
    path = tmp_path / "profiles.yaml"
    path.write_text(
        """
allowed_verification_executables: [pytest]
agents:
  backend:
    context_paths: [server]
    verification:
      - argv: [mvn, test]
        cwd: server
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not allowlisted"):
        load_execution_profiles(path)


def test_execution_profiles_load_safe_commands(tmp_path: Path):
    path = tmp_path / "profiles.yaml"
    path.write_text(
        """
allowed_verification_executables: [pytest, mvn]
agents:
  backend:
    context_paths: [server/pom.xml, .agent/project.yaml]
    read_scope: [server/**, .agent/**]
    write_scope: [server/**]
    deny_scope: [database/**, miniapp/**]
    verification:
      - argv: [mvn, test, -q]
        cwd: server
""".strip(),
        encoding="utf-8",
    )
    loaded = load_execution_profiles(path)
    profile = loaded.profiles["backend"]
    assert loaded.allowed_executables == {"pytest", "mvn"}
    assert profile.verification[0].argv == ["mvn", "test", "-q"]
    assert profile.read_scope == ["server/**", ".agent/**"]
    assert profile.write_scope == ["server/**"]
    assert profile.deny_scope == ["database/**", "miniapp/**"]


def test_execution_profile_blocks_planner_scope_expansion():
    profile = AgentExecutionProfile(
        context_paths=[],
        read_scope=["server/**"],
        write_scope=["server/**"],
        deny_scope=["database/**"],
    )
    task = TaskDraft(
        id="TASK-980101",
        requirement_ids=["REQ-980001"],
        adr_ids=["ADR-980001"],
        assigned_agent="backend",
        dependencies=[],
        scope=TaskScope(
            read=["server/**"],
            write=["**"],
            deny=["database/**"],
        ),
        acceptance=["backend change verified"],
        verification=[],
    )
    with pytest.raises(ValueError, match="expanded write scope"):
        AutonomousDevelopmentPipeline._validate_task_profile_scope(task, profile)


def test_execution_profile_allows_concrete_paths_inside_glob_and_inherits_denies():
    profile = AgentExecutionProfile(
        context_paths=["database/README.md", ".agent/project.yaml"],
        read_scope=["database/**", ".agent/**"],
        write_scope=["database/**"],
        deny_scope=["server/**", "miniapp/**"],
    )
    task = TaskDraft(
        id="TASK-980100",
        requirement_ids=["REQ-980100"],
        adr_ids=["ADR-980100"],
        assigned_agent="database",
        dependencies=[],
        scope=TaskScope(
            read=["database/README.md"],
            write=["database/migrations/V980100__points.sql"],
            deny=[],
        ),
        acceptance=["migration verified"],
        verification=[],
    )

    AutonomousDevelopmentPipeline._validate_task_profile_scope(task, profile)

    assert "database/migrations/V980100__points.sql" in task.scope.write
    assert ".agent/project.yaml" in task.scope.read
    assert "server/**" in task.scope.deny
    assert "miniapp/**" in task.scope.deny


def test_coding_runtime_retries_bad_evidence_before_write(tmp_path: Path):
    evidence_path = tmp_path / ".agent/tasks/TASK-980101.yaml"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text('id: TASK-980101\n', encoding="utf-8")

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def complete_model(self, system, user, schema):
            self.calls += 1
            if self.calls == 1:
                assert "AVAILABLE EVIDENCE IDS" in user
                return AgentAction(
                    status="SUCCESS",
                    evidence=["database/README.md"],
                    operations=[FileOperation(op="write_text", path="out.txt", content="bad")],
                )
            assert "ACTION REJECTED BEFORE ANY FILE WRITE" in user
            return AgentAction(
                status="SUCCESS",
                evidence=["TASK-980101"],
                operations=[FileOperation(op="write_text", path="out.txt", content="good")],
            )

    task = TaskDraft(
        id="TASK-980101",
        requirement_ids=["REQ-980001"],
        adr_ids=["ADR-980001"],
        assigned_agent="backend",
        dependencies=[],
        scope=TaskScope(read=[], write=["out.txt"], deny=[]),
        acceptance=["write accepted only with valid evidence"],
        verification=[],
    )
    client = FakeClient()
    result = LiveCodingRuntime(client, tmp_path, set(), max_attempts=2).execute(task, [], [])
    assert result.status == "SUCCESS"
    assert result.attempts == 2
    assert client.calls == 2
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "good"


def test_external_workflow_exists():
    workflow = Path(".github/workflows/agentforge-external-live.yml")
    assert workflow.exists()
    text = workflow.read_text(encoding="utf-8")
    assert "AGENTFORGE_LLM_API_KEY" in text
    assert "agentforge model-check" in text
