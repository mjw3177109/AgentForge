from pathlib import Path
import json
import yaml
from agentforge.errors import ProtocolError

class ProtocolLoader:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()

    def load(self, rel: str):
        path = self.repo / rel
        if path.is_symlink():
            raise ProtocolError(f"Protocol symlink denied: {rel}")
        if not path.is_file():
            raise ProtocolError(f"Protocol file missing: {rel}")
        text = path.read_text("utf-8")
        return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
