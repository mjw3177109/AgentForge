from __future__ import annotations

from dataclasses import dataclass

from agentforge.contracts import ArchitectureDraft, RequirementDraft, TaskBundle
from agentforge.llm import OpenAICompatibleClient


SYSTEM_RULES = """You are an AgentForge planning agent.
Return JSON only. Do not use Markdown.
Never invent missing business facts. Keep explicit out-of-scope items out of the implementation plan.
Do not write code. Do not change the requested technology stack.
Treat VERIFIED PROJECT CONTEXT as repository facts, not as user wishes.
"""


@dataclass(slots=True)
class LivePlan:
    requirement: RequirementDraft
    architecture: ArchitectureDraft
    tasks: TaskBundle


class LivePlanningPipeline:
    def __init__(self, client: OpenAICompatibleClient):
        self.client = client

    def plan(
        self,
        request: str,
        requirement_id: str = "REQ-900001",
        adr_id: str = "ADR-900001",
        *,
        project_context: str = "",
        task_constraints: str = "",
    ) -> LivePlan:
        context = ""
        if project_context.strip():
            context = f"\n\nVERIFIED PROJECT CONTEXT:\n{project_context.strip()}"

        req = self.client.complete_model(
            SYSTEM_RULES,
            f"Convert this user request into a requirement. The id MUST be {requirement_id}. Request: {request}{context}",
            RequirementDraft,
        )
        if req.id != requirement_id:
            raise ValueError(f"Requirement agent changed assigned id: {req.id}")

        adr = self.client.complete_model(
            SYSTEM_RULES,
            "Design architecture for this requirement. "
            f"The ADR id MUST be {adr_id}; requirement_ids MUST include {req.id}; evidence MUST include {req.id}. "
            f"Requirement JSON: {req.model_dump_json()}{context}",
            ArchitectureDraft,
        )
        if adr.id != adr_id or req.id not in adr.requirement_ids or req.id not in adr.evidence:
            raise ValueError("Architecture output is not traceable to the requirement")

        constraints = ""
        if task_constraints.strip():
            constraints = (
                "\n\nORCHESTRATOR TASK CONSTRAINTS (mandatory; these are not optional suggestions):\n"
                + task_constraints.strip()
            )
        tasks = self.client.complete_model(
            SYSTEM_RULES,
            "Create the minimal dependency-aware task DAG. Every task must reference the requirement and ADR. "
            "Do not create tasks for modules explicitly marked change_required=false. "
            "Task scope entries must be repository-relative paths/globs, never semantic descriptions. "
            f"Requirement JSON: {req.model_dump_json()}\nArchitecture JSON: {adr.model_dump_json()}"
            f"{context}{constraints}",
            TaskBundle,
        )
        self._guard_scope(req, adr, tasks)
        return LivePlan(req, adr, tasks)

    @staticmethod
    def _guard_scope(req: RequirementDraft, adr: ArchitectureDraft, bundle: TaskBundle) -> None:
        ids = {task.id for task in bundle.tasks}
        for task in bundle.tasks:
            if req.id not in task.requirement_ids:
                raise ValueError(f"{task.id} lost requirement traceability")
            if adr.id not in task.adr_ids:
                raise ValueError(f"{task.id} lost ADR traceability")
            missing_deps = [dep for dep in task.dependencies if dep not in ids]
            if missing_deps:
                raise ValueError(f"{task.id} has unknown dependencies: {missing_deps}")

        for module, config in adr.decision.items():
            if isinstance(config, dict) and config.get("change_required") is False:
                forbidden = module.lower()
                for task in bundle.tasks:
                    if task.assigned_agent.lower() == forbidden:
                        raise ValueError(f"Planner expanded scope into {module} although change_required=false")
