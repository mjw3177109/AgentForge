import json
from pathlib import Path
import httpx
import pytest
from agentforge.errors import EvidenceError, PolicyDenied
from agentforge.llm.base import AgentDriver
from agentforge.llm.openai_compatible import OpenAICompatibleDriver
from agentforge.models import AgentAction
from agentforge.runtime import ConstrainedAgentRuntime


def test_openai_compatible_parses_and_retries(monkeypatch):
    calls = {"n": 0}
    action = {"status":"SUCCESS","summary":"ok","evidence":["REQ-000001"],"operations":[],"block":None}
    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error":"busy"})
        return httpx.Response(200, json={"choices":[{"message":{"content":"```json\n" + json.dumps(action) + "\n```"}}]})
    monkeypatch.setattr("time.sleep", lambda _: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    driver = OpenAICompatibleDriver("https://llm.local/v1", "secret", "model-x", retries=1, client=client)
    out = driver.execute("prompt", {})
    assert out.status == "SUCCESS"
    assert calls["n"] == 2


def test_openai_compatible_rejects_non_action_json():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices":[{"message":{"content":"{\"hello\":\"world\"}"}}]})))
    with pytest.raises(RuntimeError):
        OpenAICompatibleDriver("https://llm.local/v1", "", "model", retries=0, client=client).execute("prompt", {})


class StaticDriver(AgentDriver):
    def __init__(self, action): self.action = AgentAction.model_validate(action)
    def execute(self, prompt, context): return self.action


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".agent/tasks").mkdir(parents=True)
    (repo / ".agent/requirements").mkdir(parents=True)
    (repo / "server").mkdir()
    (repo / "miniapp").mkdir()
    (repo / ".agent/constitution.md").write_text("Do not guess.\n", encoding="utf-8")
    (repo / ".agent/requirements/REQ-000001.yaml").write_text("id: REQ-000001\ntitle: Demo\nstatus: READY\nacceptance: [works]\n", encoding="utf-8")
    (repo / ".agent/tasks/TASK-000001.yaml").write_text("id: TASK-000001\nrequirement_ids: [REQ-000001]\nassigned_agent: backend\ndependencies: []\nscope:\n  read: ['.agent/**', 'server/**']\n  write: ['server/**']\n  deny: ['miniapp/**']\nacceptance: [works]\nstatus: READY\n", encoding="utf-8")
    (repo / "server/existing.txt").write_text("safe", encoding="utf-8")
    return repo


def test_runtime_applies_evidence_backed_in_scope_action(tmp_path):
    repo = make_repo(tmp_path)
    action = {"status":"SUCCESS","summary":"write","evidence":["TASK-000001","REQ-000001"],"operations":[{"type":"write_file","path":"server/new.txt","content":"ok"}],"block":None}
    result = ConstrainedAgentRuntime(repo, StaticDriver(action)).run_task("TASK-000001")
    assert result.status == "SUCCESS"
    assert (repo / "server/new.txt").read_text() == "ok"


def test_runtime_rejects_agent_scope_escape(tmp_path):
    repo = make_repo(tmp_path)
    action = {"status":"SUCCESS","summary":"bad","evidence":["TASK-000001"],"operations":[{"type":"write_file","path":"miniapp/pwn.js","content":"x"}],"block":None}
    with pytest.raises(PolicyDenied):
        ConstrainedAgentRuntime(repo, StaticDriver(action)).run_task("TASK-000001")


def test_runtime_rejects_unknown_evidence(tmp_path):
    repo = make_repo(tmp_path)
    action = {"status":"SUCCESS","summary":"bad","evidence":["REQ-999999"],"operations":[],"block":None}
    with pytest.raises(EvidenceError):
        ConstrainedAgentRuntime(repo, StaticDriver(action)).run_task("TASK-000001")
