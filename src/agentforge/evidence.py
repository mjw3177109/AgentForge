from pathlib import Path
import json
import yaml
from agentforge.errors import EvidenceError

ID_PREFIXES = ("REQ-", "ADR-", "TASK-", "FACT-", "API-", "DB-", "RULE-", "SEC-", "MEM-")

class EvidenceIndex:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        self.ids: set[str] = set()

    def build(self) -> "EvidenceIndex":
        root = self.repo / ".agent"
        if not root.exists():
            return self
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in {".yaml", ".yml", ".json"}:
                continue
            try:
                data = json.loads(path.read_text("utf-8")) if path.suffix == ".json" else yaml.safe_load(path.read_text("utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                value = data.get("id") or data.get("handoff_id")
                if isinstance(value, str) and value.startswith(ID_PREFIXES):
                    self.ids.add(value)
        return self

    def require(self, evidence: list[str]) -> None:
        missing = [item for item in evidence if item not in self.ids]
        if missing:
            raise EvidenceError(f"Unknown evidence: {missing}")
