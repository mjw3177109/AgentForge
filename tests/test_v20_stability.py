"""Offline chaos and contract tests for the V2.0 stability gate."""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from agentforge.llm import LLMError, OpenAICompatibleClient


_SPEC = importlib.util.spec_from_file_location(
    "v20_stability_runner", Path(__file__).resolve().parents[1] / "scripts/run_v20_stability.py"
)
assert _SPEC is not None and _SPEC.loader is not None
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


class Expected(BaseModel):
    ok: bool
    count: int


class FaultServer(BaseHTTPRequestHandler):
    failures = []
    request_count = 0
    user_prompts = []

    def log_message(self, *_args):
        return

    def do_POST(self):
        cls = type(self)
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        cls.request_count += 1
        cls.user_prompts.append(body["messages"][-1]["content"])
        status = cls.failures.pop(0) if cls.failures else 200
        if status == 200:
            content = json.dumps({
                "choices": [{"message": {"content": json.dumps({"ok": True, "count": 7})}}]
            }).encode("utf-8")
        else:
            content = b'{"error":{"message":"temporary provider error"}}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


@pytest.fixture
def fault_http():
    cls = type("IsolatedFaultHandler", (FaultServer,),
               {"failures": [], "request_count": 0, "user_prompts": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, cls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("http_error", [429, 500, 502, 503])
def test_transient_provider_http_failure_recovers(fault_http, monkeypatch, http_error):
    server, handler = fault_http
    handler.failures[:] = [http_error]
    monkeypatch.setattr("agentforge.llm.time.sleep", lambda _n: None)
    client = OpenAICompatibleClient(
        base_url=f"http://127.0.0.1:{server.server_port}",
        api_key="test-key", model="offline-fault-model", max_attempts=3,
    )
    got = client.complete_model("system", "task", Expected)
    assert got.ok and got.count == 7
    assert handler.request_count == 2
    assert "JSON Schema" in handler.user_prompts[0]


def test_permanent_provider_failure_never_returns_fake_success(fault_http, monkeypatch):
    server, handler = fault_http
    handler.failures[:] = [503, 503, 503]
    monkeypatch.setattr("agentforge.llm.time.sleep", lambda _n: None)
    client = OpenAICompatibleClient(
        base_url=f"http://127.0.0.1:{server.server_port}",
        api_key="test-key", model="offline-fault-model", max_attempts=3,
    )
    with pytest.raises(LLMError, match="failed strict structured output"):
        client.complete_model("system", "task", Expected)
    assert handler.request_count == 3


def test_validation_fault_retries_without_leaking_internal_exception(monkeypatch):
    responses = iter(['{"ok":true,"count":"not-an-int"}',
                      '{"ok":true,"count":7}'])
    prompts = []
    def fake_request(self, _system, user):
        prompts.append(user)
        return next(responses)
    monkeypatch.setattr(OpenAICompatibleClient, "_request", fake_request)
    monkeypatch.setattr("agentforge.llm.time.sleep", lambda _n: None)
    client = OpenAICompatibleClient("https://example.invalid", "key", "model", max_attempts=2)
    got = client.complete_model("system", "task", Expected)
    assert got.count == 7
    assert len(prompts) == 2 and "Validation feedback:" in prompts[-1]


def _success_result():
    names = ["database", "backend", "miniapp", "admin"]
    return {"status": "SUCCESS", "review": {"status": "APPROVE"},
            "pr_url": None,
            "task_runs": [
                {"task_id": f"TASK-{i+1}", "agent": agent, "status": "SUCCESS",
                 "commit": "a" * 40, "message": "All verification gates passed."}
                for i, agent in enumerate(names)
            ]}


def test_success_gate_requires_all_four_agents_and_reviewer_approval():
    assert gate.assess_result(_success_result(), 0)[0] == "passed"
    payload = _success_result()
    payload["task_runs"].pop(3)
    assert gate.assess_result(payload, 0)[0] == "task_records"
    payload = _success_result()
    payload["review"]["status"] = "REQUEST_CHANGES"
    assert gate.assess_result(payload, 0)[0] == "review"


def test_gate_enforces_repair_budget_and_blocks_fake_green():
    payload = _success_result()
    for i in range(3):
        payload["task_runs"].append({
            "task_id": "TASK-2", "agent": "backend", "status": "SUCCESS",
            "commit": "b" * 40,
            "message": f"review repair round {i+1}, task attempt {i+1}/2: verified",
        })
    assert gate.assess_result(payload, 0)[0] == "repair_budget"
    assert gate.assess_result(_success_result(), 2)[0] != "passed"
    assert gate.assess_result(None, 0)[0] == "transport_or_protocol"
    payload = _success_result()
    payload["pr_url"] = "https://example.invalid/pr"
    assert gate.assess_result(payload, 0)[0] == "release_safety"


@pytest.mark.parametrize("stage,detail,expected", [
    ("review", "Reviewer REQUEST_CHANGES", "REVIEW_SEMANTICS"),
    ("execution", "provider returned 429", "LLM_RATE_LIMIT"),
    ("execution", "timed out", "TIMEOUT"),
    ("maven", "test error", "MAVEN_CONTRACT"),
    ("mysql_schema", "schema error", "MYSQL_CONTRACT"),
    ("npm_vite", "bundle error", "NODE_CONTRACT"),
    ("release_safety", "unexpected PR", "UNSAFE_RELEASE"),
])
def test_failure_classification_is_explicit(stage, detail, expected):
    assert gate.classify_failure(stage, detail) == expected


def test_verified_cross_stack_contracts_match_without_making_up_admin_scope():
    root = Path(__file__).resolve().parents[1] / "benchmarks/v18_hardened/contracts"
    contract = yaml.safe_load((root / "API-POINTS-980100.yaml").read_text("utf-8"))
    assert contract["public_user_api"]["balance"]["path"] == contract["admin"]["must_load_authoritative_balance"]
    assert contract["public_user_api"]["ledger"]["path"] == contract["admin"]["must_load_ledger"]
    assert contract["public_user_api"]["balance"]["path"] == contract["miniapp"]["balance_path"]
    assert contract["public_user_api"]["redeem_preview"]["path"] == contract["miniapp"]["redeem_preview_path"]
    assert contract["earning"]["public_endpoint"] == "forbidden"
    assert contract["earning"]["service_operation"] == "earnAfterPayment"
