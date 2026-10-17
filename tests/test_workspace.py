from pathlib import Path
import pytest
from agentforge.errors import PolicyDenied
from agentforge.policy import PolicyEngine
from agentforge.workspace import SafeWorkspace

def test_write_scope(tmp_path: Path):
    ws = SafeWorkspace(tmp_path, PolicyEngine(write=["server/**"], deny=[]))
    ws.write_text("server/ok.txt", "ok")
    assert (tmp_path / "server/ok.txt").read_text() == "ok"
    with pytest.raises(PolicyDenied): ws.write_text("server/../miniapp/pwn.txt", "x")
