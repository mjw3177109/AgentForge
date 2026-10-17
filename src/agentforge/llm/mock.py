from __future__ import annotations
from agentforge.llm.base import AgentDriver
from agentforge.models import AgentAction


class MockAgentDriver(AgentDriver):
    def execute(self, prompt: str, context: dict) -> AgentAction:
        task = context["task"]
        return AgentAction.model_validate({
            "status": "SUCCESS",
            "summary": "Mock deterministic action",
            "evidence": [task["id"], *task.get("requirement_ids", [])],
            "operations": [],
            "block": None,
        })
