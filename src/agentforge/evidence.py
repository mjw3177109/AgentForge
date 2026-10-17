from __future__ import annotations
from pathlib import Path
import json
import re
import yaml
from agentforge.errors import EvidenceError
from agentforge.util import ensure_within

ID_RE = re.compile(r"^(?:REQ|ADR|TASK|HO|FACT|API|DB|RULE|SEC|MEM)-[A-Z0-9-]+$")


class EvidenceIndex:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        self.ids: set[str] = set()

    def build(self) -> "EvidenceIndex":
        self.ids.clear()
        root = self.repo / ".agent"
        if not root.exists() or root.is_symlink():
            return self
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in {".yaml", ".yml", ".json"}:
                continue
            try:
                safe = ensure_within(root, path)
                text = safe.read_text("utf-8")
                data = json.loads(text) if safe.suffix == ".json" else yaml.safe_load(text)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            for key in ("id", "handoff_id"):
                value = data.get(key)
                if isinstance(value, str) and ID_RE.match(value):
                    self.ids.add(value)
        return self

    def require(self, evidence: list[str], minimum: int = 1) -> None:
        if len(evidence) < minimum:
            raise EvidenceError("AgentAction has insufficient evidence")
        malformed = [x for x in evidence if not isinstance(x, str) or not ID_RE.match(x)]
        if malformed:
            raise EvidenceError(f"Malformed evidence IDs: {malformed}")
        missing = [x for x in evidence if x not in self.ids]
        if missing:
            raise EvidenceError(f"Unknown evidence IDs: {missing}")
