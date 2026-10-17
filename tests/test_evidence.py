from pathlib import Path
import pytest
from agentforge.evidence import EvidenceIndex
from agentforge.errors import EvidenceError

def test_root_ids_only(tmp_path: Path):
    p = tmp_path / ".agent" / "requirements"; p.mkdir(parents=True)
    (p / "r.yaml").write_text("id: REQ-000001\nmeta:\n  id: REQ-999999\n", encoding="utf-8")
    idx = EvidenceIndex(tmp_path).build()
    idx.require(["REQ-000001"])
    with pytest.raises(EvidenceError): idx.require(["REQ-999999"])
