import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentforge.live import LivePlanningPipeline
from agentforge.llm import OpenAICompatibleClient


def test_planner_cannot_reintroduce_out_of_scope_admin():
    responses = [
        {"id":"REQ-900001","title":"收藏","actors":[],"modules":["favorite"],"business_rules":[],"acceptance":["works"],"out_of_scope":["管理后台收藏管理"]},
        {"id":"ADR-900001","requirement_ids":["REQ-900001"],"decision":{"admin":{"change_required":False}},"evidence":["REQ-900001"]},
        {"tasks":[{"id":"TASK-900001","requirement_ids":["REQ-900001"],"adr_ids":["ADR-900001"],"assigned_agent":"admin","dependencies":[],"scope":{"read":[],"write":["admin-web/**"],"deny":[]},"acceptance":["admin page"],"verification":[]}]},
    ]
    class H(BaseHTTPRequestHandler):
        calls = 0
        def log_message(self, *_): pass
        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0")); self.rfile.read(n)
            value = responses[min(H.calls, 2)]; H.calls += 1
            body = json.dumps({"choices":[{"message":{"content":json.dumps(value, ensure_ascii=False)}}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = OpenAICompatibleClient(f"http://127.0.0.1:{server.server_port}", "", "fake")
        with pytest.raises(ValueError, match="expanded scope"):
            LivePlanningPipeline(client).plan("增加收藏")
    finally:
        server.shutdown()
