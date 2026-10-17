from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agentforge.coding import LiveCodingRuntime, VerificationRunner, VerificationSpec
from agentforge.contracts import TaskDraft, TaskScope
from agentforge.errors import EvidenceError, PolicyDenied
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


def make_repo(tmp_path: Path) -> tuple[Path, TaskDraft]:
    repo = tmp_path / "repo"
    (repo / ".agent/requirements").mkdir(parents=True)
    (repo / ".agent/tasks").mkdir(parents=True)
    (repo / "target_tests").mkdir(parents=True)
    (repo / ".agent/requirements/REQ-000001.yaml").write_text(
        "id: REQ-000001\ntitle: calculator\n", encoding="utf-8"
    )
    (repo / ".agent/tasks/TASK-000101.yaml").write_text(
        "id: TASK-000101\nrequirement_ids: [REQ-000001]\n", encoding="utf-8"
    )
    (repo / "target_tests/test_calc.py").write_text(
        "from app.calc import add\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    task = TaskDraft(
        id="TASK-000101",
        requirement_ids=["REQ-000001"],
        adr_ids=[],
        assigned_agent="backend",
        dependencies=[],
        scope=TaskScope(
            read=["app/**", "target_tests/**"],
            write=["app/**"],
            deny=[".agent/**"],
        ),
        acceptance=["add(2,3) returns 5"],
        verification=["pytest"],
    )
    return repo, task


def client_for(server) -> OpenAICompatibleClient:
    host, port = server.server_address
    return OpenAICompatibleClient(
        base_url=f"http://{host}:{port}",
        api_key="test",
        model="fake-live-coder",
        max_attempts=1,
    )


def test_live_coding_repair_loop(tmp_path):
    repo, task = make_repo(tmp_path)
    first = {
        "status": "SUCCESS",
        "summary": "initial implementation",
        "evidence": ["REQ-000001", "TASK-000101"],
        "operations": [{"op": "write_text", "path": "app/calc.py", "content": "def add(a, b):\n    return a - b\n"}],
    }
    repair = {
        "status": "SUCCESS",
        "summary": "repair failed addition test",
        "evidence": ["REQ-000001", "TASK-000101"],
        "operations": [{"op": "write_text", "path": "app/calc.py", "content": "def add(a, b):\n    return a + b\n"}],
    }
    server, handler = start_server([first, repair])
    try:
        runtime = LiveCodingRuntime(
            client_for(server),
            repo,
            allowed_verification_executables={Path(sys.executable).name},
            max_attempts=2,
        )
        result = runtime.execute(
            task,
            context_paths=["target_tests/test_calc.py"],
            verification=[VerificationSpec(argv=[sys.executable, "-m", "pytest", "-q", "target_tests/test_calc.py"])],
        )
        assert result.status == "SUCCESS"
        assert result.attempts == 2
        assert "return a + b" in (repo / "app/calc.py").read_text("utf-8")
        assert len(handler.requests) == 2
        second_user = handler.requests[1]["messages"][1]["content"]
        assert "VERIFICATION FAILED" in second_user
        assert "test_add" in second_user
    finally:
        server.shutdown()


def test_missing_evidence_never_writes(tmp_path):
    repo, task = make_repo(tmp_path)
    response = {
        "status": "SUCCESS",
        "evidence": ["FACT-NOT-REAL"],
        "operations": [{"op": "write_text", "path": "app/x.py", "content": "x = 1\n"}],
    }
    server, _ = start_server([response])
    try:
        runtime = LiveCodingRuntime(client_for(server), repo, {Path(sys.executable).name})
        with pytest.raises(EvidenceError):
            runtime.execute(task, [], [])
        assert not (repo / "app/x.py").exists()
    finally:
        server.shutdown()


def test_path_traversal_never_writes(tmp_path):
    repo, task = make_repo(tmp_path)
    response = {
        "status": "SUCCESS",
        "evidence": ["REQ-000001", "TASK-000101"],
        "operations": [{"op": "write_text", "path": "../escape.py", "content": "pwned\n"}],
    }
    server, _ = start_server([response])
    try:
        runtime = LiveCodingRuntime(client_for(server), repo, {Path(sys.executable).name})
        with pytest.raises(PolicyDenied):
            runtime.execute(task, [], [])
        assert not (tmp_path / "escape.py").exists()
    finally:
        server.shutdown()


def test_model_can_block_without_mutation(tmp_path):
    repo, task = make_repo(tmp_path)
    response = {
        "status": "BLOCKED",
        "summary": "missing contract",
        "block_reason": "Need an API contract before implementation",
        "evidence": [],
        "operations": [],
    }
    server, _ = start_server([response])
    try:
        runtime = LiveCodingRuntime(client_for(server), repo, {Path(sys.executable).name})
        result = runtime.execute(task, [], [])
        assert result.status == "BLOCKED"
        assert "API contract" in result.message
        assert not (repo / "app").exists()
    finally:
        server.shutdown()


def test_verification_executable_is_allowlisted(tmp_path):
    repo, _ = make_repo(tmp_path)
    runner = VerificationRunner(repo, allowed_executables={"python"})
    with pytest.raises(PolicyDenied):
        runner.run([VerificationSpec(argv=["bash", "-lc", "echo nope"])])


def test_verification_side_effects_stay_in_disposable_copy(tmp_path):
    repo, _ = make_repo(tmp_path)
    runner = VerificationRunner(repo, allowed_executables={Path(sys.executable).name})
    result = runner.run([
        VerificationSpec(argv=[
            sys.executable,
            "-c",
            "from pathlib import Path; Path('verification-side-effect.txt').write_text('sandbox only')",
        ])
    ])
    assert result[0].success is True
    assert not (repo / "verification-side-effect.txt").exists()
