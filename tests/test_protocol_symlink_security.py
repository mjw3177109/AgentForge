from pathlib import Path
import pytest
from agentforge.errors import ProtocolError
from agentforge.protocol import ProtocolLoader

def test_protocol_symlink_denied(tmp_path: Path):
    outside = tmp_path / "outside.yaml"; outside.write_text("id: REQ-000001\n")
    agent = tmp_path / ".agent"; agent.mkdir()
    link = agent / "project.yaml"
    try: link.symlink_to(outside)
    except OSError: pytest.skip("symlink unavailable")
    with pytest.raises(ProtocolError): ProtocolLoader(tmp_path).load(".agent/project.yaml")
