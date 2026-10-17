from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import yaml
from agentforge.errors import ProtocolError
from agentforge.util import ensure_within, load_yaml


class ProtocolLoader:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()

    def load(self, rel: str):
        path = self.repo / rel
        if path.is_symlink():
            raise ProtocolError(f"Protocol symlink denied: {rel}")
        if not path.is_file():
            raise ProtocolError(f"Protocol file missing: {rel}")
        try:
            ensure_within(self.repo, path)
        except ValueError as exc:
            raise ProtocolError(f"Protocol path escapes repository: {rel}") from exc
        text = path.read_text("utf-8")
        return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


@dataclass
class ProjectProtocol:
    repo_root: Path

    def __post_init__(self):
        self.repo_root = self.repo_root.resolve()

    @property
    def agent_root(self) -> Path:
        return self.repo_root / ".agent"

    def _safe(self, path: Path) -> Path:
        if path.is_symlink():
            raise ProtocolError(f"Symlink protocol files are not allowed: {path}")
        try:
            return ensure_within(self.agent_root, path)
        except ValueError as exc:
            raise ProtocolError(f"Protocol path escapes .agent: {path}") from exc

    def load_agent_yaml(self, path: Path) -> dict[str, Any]:
        path = self._safe(path)
        if not path.is_file():
            raise ProtocolError(f"AgentForge protocol file not found: {path}")
        data = load_yaml(path)
        if not isinstance(data, dict):
            raise ProtocolError(f"Protocol YAML must contain an object: {path}")
        return data

    def project(self) -> dict[str, Any]:
        return self.load_agent_yaml(self.agent_root / "project.yaml")

    def task(self, task_id: str) -> dict[str, Any]:
        return self.load_agent_yaml(self.agent_root / "tasks" / f"{task_id}.yaml")

    def requirement(self, req_id: str) -> dict[str, Any]:
        return self.load_agent_yaml(self.agent_root / "requirements" / f"{req_id}.yaml")

    def adr(self, adr_id: str) -> dict[str, Any]:
        return self.load_agent_yaml(self.agent_root / "decisions" / f"{adr_id}.yaml")

    def agent_definition(self, agent_id: str) -> dict[str, Any]:
        local = self.agent_root / "agents" / f"{agent_id}.yaml"
        if local.exists():
            return self.load_agent_yaml(local)
        bundled = Path(__file__).resolve().parents[3] / "protocol_bundle" / "agents" / f"{agent_id}.yaml"
        if bundled.is_file():
            data = load_yaml(bundled)
            if isinstance(data, dict):
                return data
        raise ProtocolError(f"Agent definition not found: {agent_id}")

    def verification_policy(self) -> dict[str, Any]:
        path = self.agent_root / "policies" / "verification.yaml"
        if not path.exists():
            return {"checks": {}}
        return self.load_agent_yaml(path)
