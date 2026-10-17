from __future__ import annotations
from pathlib import Path
from typing import Any
from agentforge.policy import PolicyEngine
from agentforge.protocol.loader import ProjectProtocol
from agentforge.util import ensure_within, stable_hash


class ContextBuilder:
    def __init__(self, repo_root: Path, max_files: int = 40, max_file_bytes: int = 100_000):
        self.repo_root = repo_root.resolve()
        self.protocol = ProjectProtocol(self.repo_root)
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes

    def build(self, task_id: str) -> dict[str, Any]:
        task = self.protocol.task(task_id)
        agent = self.protocol.agent_definition(task["assigned_agent"])
        policy = PolicyEngine(task, agent)
        requirements = [self.protocol.requirement(x) for x in task.get("requirement_ids", [])]
        adrs = [self.protocol.adr(x) for x in task.get("adr_ids", [])]
        files = []
        for path in sorted(self.repo_root.rglob("*")):
            if len(files) >= self.max_files or not path.is_file() or path.is_symlink():
                continue
            lexical = path.relative_to(self.repo_root).as_posix()
            if lexical.startswith((".git/", ".agent/")):
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
        constitution = (self.repo_root / ".agent" / "constitution.md").read_text("utf-8")
        data = {"task": task, "agent": agent, "constitution": constitution, "requirements": requirements, "adrs": adrs, "files": files}
        data["context_hash"] = stable_hash(data)
        return data

    @staticmethod
    def to_prompt(ctx: dict[str, Any]) -> str:
        import json
        return (
            "You are a constrained AgentForge software agent. Follow the constitution and task exactly. "
            "Do not invent missing project facts. If a critical fact is missing, return BLOCKED with zero operations. "
            "Return ONLY JSON matching AgentAction.\n\nCONTEXT:\n" + json.dumps(ctx, ensure_ascii=False, indent=2)
        )
