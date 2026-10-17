from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from agentforge.context import ContextBuilder
from agentforge.evidence import EvidenceIndex
from agentforge.llm.base import AgentDriver
from agentforge.policy import PolicyEngine
from agentforge.protocol.loader import ProjectProtocol
from agentforge.workspace import WorkspaceMutator


@dataclass
class RuntimeResult:
    status: str
    summary: str
    context_hash: str
    changed_files: list[str]
    block: dict | None = None


class ConstrainedAgentRuntime:
    """Execute exactly one task without granting the model direct tools.

    The model receives a scoped context and can only return AgentAction JSON.
    Evidence and effective task+agent permissions are checked before filesystem
    mutation.
    """

    def __init__(self, repo_root: Path, driver: AgentDriver):
        self.repo_root = repo_root.resolve()
        self.driver = driver

    def run_task(self, task_id: str) -> RuntimeResult:
        protocol = ProjectProtocol(self.repo_root)
        context = ContextBuilder(self.repo_root).build(task_id)
        action = self.driver.execute(ContextBuilder.to_prompt(context), context)
        if action.status == "BLOCKED":
            return RuntimeResult("BLOCKED", action.summary, context["context_hash"], [], action.block.model_dump() if action.block else None)
        EvidenceIndex(self.repo_root).build().require(action.evidence, minimum=1)
        task = protocol.task(task_id)
        agent = protocol.agent_definition(task["assigned_agent"])
        changed = WorkspaceMutator(self.repo_root, PolicyEngine(task, agent)).apply(action)
        return RuntimeResult("SUCCESS", action.summary, context["context_hash"], changed)
