from __future__ import annotations
from pathlib import Path
from typing import Any
import json
import yaml
from agentforge.policy import PolicyEngine
from agentforge.protocol.loader import ProjectProtocol
from agentforge.util import ensure_within, stable_hash


class ContextBuilder:
    """Build a bounded, evidence-oriented context package for one task.

    Source code is filtered by effective task+agent read scope. Project facts,
    contracts, DB contracts and only dependency-related handoffs are supplied as
    structured data, while long-term memory is read from the repository rather
    than from conversation history.
    """

    def __init__(self, repo_root: Path, max_files: int = 40, max_file_bytes: int = 100_000, max_protocol_items: int = 50):
        self.repo_root = repo_root.resolve()
        self.protocol = ProjectProtocol(self.repo_root)
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.max_protocol_items = max_protocol_items

    def _yaml_collection(self, relative_dir: str, predicate=None) -> list[dict[str, Any]]:
        root = self.repo_root / ".agent" / relative_dir
        if not root.is_dir() or root.is_symlink():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.yaml")):
            if len(items) >= self.max_protocol_items or not path.is_file() or path.is_symlink():
                continue
            try:
                ensure_within(self.repo_root / ".agent", path)
                value = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(value, dict):
                continue
            if predicate is None or predicate(value):
                items.append(value)
        return items

    def _memory(self) -> list[dict[str, str]]:
        root = self.repo_root / ".agent" / "memory"
        if not root.is_dir() or root.is_symlink():
            return []
        result = []
        for path in sorted(root.glob("*.md"))[:20]:
            if path.is_symlink() or not path.is_file():
                continue
            try:
                ensure_within(self.repo_root / ".agent", path)
                text = path.read_text(encoding="utf-8")[:50_000]
            except Exception:
                continue
            result.append({"path": path.relative_to(self.repo_root).as_posix(), "content": text})
        return result

    def build(self, task_id: str) -> dict[str, Any]:
        task = self.protocol.task(task_id)
        agent = self.protocol.agent_definition(task["assigned_agent"])
        policy = PolicyEngine(task, agent)
        requirements = [self.protocol.requirement(x) for x in task.get("requirement_ids", [])]
        adrs = [self.protocol.adr(x) for x in task.get("adr_ids", [])]
        dependency_ids = set(task.get("dependencies", []))
        handoffs = self._yaml_collection("handoffs", lambda item: item.get("task_id") in dependency_ids)
        facts = self._yaml_collection("facts")
        contracts = self._yaml_collection("contracts")
        database_contracts = self._yaml_collection("database")

        files = []
        for path in sorted(self.repo_root.rglob("*")):
            if len(files) >= self.max_files or not path.is_file() or path.is_symlink():
                continue
            lexical = path.relative_to(self.repo_root).as_posix()
            if lexical.startswith((".git/", ".agent/", ".agentforge")):
                continue
            try:
                resolved = ensure_within(self.repo_root, path)
            except ValueError:
                continue
            rel = resolved.relative_to(self.repo_root).as_posix()
            if not policy.can_read(rel):
                continue
            try:
                if resolved.stat().st_size > self.max_file_bytes:
                    continue
                content = resolved.read_text("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            files.append({"path": rel, "content": content})

        constitution_path = self.repo_root / ".agent" / "constitution.md"
        constitution = constitution_path.read_text("utf-8") if constitution_path.is_file() and not constitution_path.is_symlink() else ""
        data = {
            "task": task,
            "agent": agent,
            "constitution": constitution,
            "requirements": requirements,
            "adrs": adrs,
            "facts": facts,
            "contracts": contracts,
            "database_contracts": database_contracts,
            "handoffs": handoffs,
            "memory": self._memory(),
            "files": files,
        }
        data["context_hash"] = stable_hash(data)
        return data

    @staticmethod
    def to_prompt(ctx: dict[str, Any]) -> str:
        return (
            "You are a constrained AgentForge software agent. Follow the constitution and task exactly. "
            "Treat repository facts/contracts/handoffs/memory as evidence; do not invent replacements. "
            "Do not invent missing business rules, auth, APIs, DB fields, dependencies, or external service behavior. "
            "If a critical fact is missing, return BLOCKED with zero operations. "
            "Return ONLY JSON matching AgentAction.\n\nCONTEXT:\n" + json.dumps(ctx, ensure_ascii=False, indent=2)
        )
