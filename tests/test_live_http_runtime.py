import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentforge.live import LivePlanningPipeline
from agentforge.llm import LLMError, OpenAICompatibleClient


RESPONSES = [
    {
        "id": "REQ-900001",
        "title": "商品收藏",
        "actors": ["CUSTOMER"],
        "modules": ["favorite"],
        "business_rules": ["同一用户和商品不可重复收藏"],
        "acceptance": ["可以收藏", "可以取消收藏"],
        "out_of_scope": ["管理后台收藏管理"],
    },
    {
        "id": "ADR-900001",
        "requirement_ids": ["REQ-900001"],
        "decision": {
            "database": {"change_required": True},
            "backend": {"change_required": True},
            "miniapp": {"change_required": True},
            "admin": {"change_required": False},
        },
        "evidence": ["REQ-900001"],
    },
    {
        "tasks": [
            {"id": "TASK-900001", "requirement_ids": ["REQ-900001"], "adr_ids": ["ADR-900001"], "assigned_agent": "database", "dependencies": [], "scope": {"read": [".agent/**"], "write": ["database/**"], "deny": []}, "acceptance": ["migration exists"], "verification": ["migration-test"]},
            {"id": "TASK-900002", "requirement_ids": ["REQ-900001"], "adr_ids": ["ADR-900001"], "assigned_agent": "backend", "dependencies": ["TASK-900001"], "scope": {"read": [".agent/**", "server/**"], "write": ["server/**"], "deny": ["miniapp/**"]}, "acceptance": ["favorite API exists"], "verification": ["mvn-test"]},
            {"id": "TASK-900003", "requirement_ids": ["REQ-900001"], "adr_ids": ["ADR-900001"], "assigned_agent": "miniapp", "dependencies": ["TASK-900002"], "scope": {"read": [".agent/**", "miniapp/**"], "write": ["miniapp/**"], "deny": ["server/**"]}, "acceptance": ["favorite toggle works"], "verification": ["npm-test"]},
        ]
    },
]


class Handler(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *_):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        json.loads(self.rfile.read(length))
        idx = min(Handler.calls, len(RESPONSES) - 1)
        Handler.calls += 1
        content = json.dumps(RESPONSES[idx], ensure_ascii=False)
        body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_live_pipeline_over_real_http_boundary():
    Handler.calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenAICompatibleClient(f"http://127.0.0.1:{server.server_port}", "test-key", "fake-model")
        plan = LivePlanningPipeline(client).plan("增加商品收藏")
        assert plan.requirement.id == "REQ-900001"
        assert plan.architecture.id == "ADR-900001"
        assert [t.assigned_agent for t in plan.tasks.tasks] == ["database", "backend", "miniapp"]
        assert Handler.calls == 3
    finally:
        server.shutdown()


def test_strict_json_retries_then_fails():
    class BadHandler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0")); self.rfile.read(length)
            body = json.dumps({"choices": [{"message": {"content": "not-json"}}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), BadHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = OpenAICompatibleClient(f"http://127.0.0.1:{server.server_port}", "", "fake", max_attempts=2)
        with pytest.raises(LLMError):
            LivePlanningPipeline(client).plan("test")
    finally:
        server.shutdown()
