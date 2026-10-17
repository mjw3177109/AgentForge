from __future__ import annotations
from abc import ABC, abstractmethod
from agentforge.models import AgentAction


class AgentDriver(ABC):
    @abstractmethod
    def execute(self, prompt: str, context: dict) -> AgentAction:
        raise NotImplementedError
