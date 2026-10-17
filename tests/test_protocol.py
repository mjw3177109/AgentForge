from pathlib import Path
from agentforge.protocol import ProtocolLoader, ProtocolValidator

def test_protocol_validation(tmp_path: Path):
    agent = tmp_path / ".agent"; agent.mkdir()
    (agent / "project.yaml").write_text("project:\n  id: P1\n  name: demo\n  version: '1'\nrepository:\n  provider: github\n  default_branch: main\nstack: {}\nrules:\n  direct_main_write: false\n  require_pr: true\n  require_ci: true\n  require_fact_reference: true\n", encoding="utf-8")
    data = ProtocolLoader(tmp_path).load(".agent/project.yaml")
    schemas = Path(__file__).parents[1] / "protocol_bundle" / "schemas"
    ProtocolValidator(schemas).validate(data, "project.schema.json")
