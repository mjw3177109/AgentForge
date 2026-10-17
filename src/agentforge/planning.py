from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import secrets

from agentforge.evidence import EvidenceIndex
from agentforge.errors import PlanningError
from agentforge.git import FeatureBranchManager, GitRepository
from agentforge.llm.base import AgentDriver
from agentforge.models import WriteFileOperation
from agentforge.policy import PolicyEngine
from agentforge.protocol.loader import ProjectProtocol
from agentforge.protocol.validator import ProtocolValidator
from agentforge.workspace import WorkspaceMutator


RUNTIME_AGENTS = {"database", "backend", "miniapp", "admin", "test", "reviewer"}
MODULE_AGENT = {"database": "database", "backend": "backend", "miniapp": "miniapp", "admin": "admin"}
MODULE_KEYWORDS = {
    "admin": ("admin", "管理后台", "后台管理"),
    "miniapp": ("miniapp", "小程序"),
    "backend": ("backend", "后端"),
    "database": ("database", "数据库"),
}


@dataclass
class PlanningResult:
    requirement_id: str
    adr_id: str
    task_ids: list[str]
    feature_branch: str
    feature_worktree: str
    planning_commit: str


def _distributed_token() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
    return f"{timestamp}-{secrets.token_hex(2).upper()}"


class FeaturePlanningPipeline:
    """Turn one natural-language requirement into REQ -> ADR -> Task DAG.

    Planning always occurs in a feature integration worktree, never in the base
    branch worktree. Planning agents can only create Core-allocated protocol
    files and cannot touch application source.
    """

    def __init__(self, repo_root: Path, driver: AgentDriver):
        self.repo_root = repo_root.resolve()
        self.driver = driver
        self.validator = ProtocolValidator()

    @staticmethod
    def _prompt(stage: str, context: dict[str, Any]) -> str:
        return (
            f"AGENTFORGE PLANNING STAGE: {stage}\n"
            "Return ONLY AgentAction JSON. Do not claim to execute tools. "
            "Do not invent missing business, authentication, API, DB or dependency facts. "
            "If a critical fact is missing, return BLOCKED with zero operations.\n\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        )

    def _apply_planning_action(
        self,
        worktree: Path,
        role: str,
        stage: str,
        context: dict[str, Any],
        allowed_paths: list[str],
        evidence_minimum: int,
    ):
        protocol = ProjectProtocol(worktree)
        agent = protocol.agent_definition(role)
        synthetic_task = {"scope": {"read": [".agent/**"], "write": allowed_paths, "deny": []}}
        action = self.driver.execute(self._prompt(stage, context), context)
        if action.status == "BLOCKED":
            return action
        if not action.operations:
            raise PlanningError(f"{stage} returned SUCCESS without an operation")
        if evidence_minimum or action.evidence:
            EvidenceIndex(worktree).build().require(action.evidence, minimum=evidence_minimum)
        allowed = set(allowed_paths)
        seen: set[str] = set()
        for operation in action.operations:
            if not isinstance(operation, WriteFileOperation):
                raise PlanningError(f"{stage} may only create protocol files with write_file")
            if operation.path not in allowed:
                raise PlanningError(f"{stage} tried to write unallocated path: {operation.path}")
            if operation.path in seen:
                raise PlanningError(f"{stage} wrote the same protocol file twice: {operation.path}")
            seen.add(operation.path)
        WorkspaceMutator(worktree, PolicyEngine(synthetic_task, agent)).apply(action)
        return action

    @staticmethod
    def _forbidden_agents(requirement: dict, adr: dict) -> set[str]:
        forbidden: set[str] = set()
        explicit = requirement.get("out_of_scope_modules", [])
        if isinstance(explicit, list):
            forbidden |= {MODULE_AGENT[x] for x in explicit if x in MODULE_AGENT}
        for item in requirement.get("out_of_scope", []) if isinstance(requirement.get("out_of_scope"), list) else []:
            text = str(item).lower()
            for module, keywords in MODULE_KEYWORDS.items():
                if any(keyword.lower() in text for keyword in keywords):
                    forbidden.add(MODULE_AGENT[module])
        decision = adr.get("decision", {})
        if isinstance(decision, dict):
            for module, agent in MODULE_AGENT.items():
                module_decision = decision.get(module)
                if isinstance(module_decision, dict) and module_decision.get("change_required") is False:
                    forbidden.add(agent)
        return forbidden

    @staticmethod
    def _topological(tasks: list[dict]) -> list[dict]:
        by_id = {task["id"]: task for task in tasks}
        if len(by_id) != len(tasks):
            raise PlanningError("Planner produced duplicate task IDs")
        remaining = set(by_id)
        done: set[str] = set()
        ordered: list[dict] = []
        while remaining:
            ready = sorted(tid for tid in remaining if set(by_id[tid].get("dependencies", [])) <= done)
            if not ready:
                raise PlanningError(f"Task DAG contains a cycle or unresolved dependency: {sorted(remaining)}")
            for tid in ready:
                ordered.append(by_id[tid])
                done.add(tid)
                remaining.remove(tid)
        return ordered

    def _validate_plan(self, worktree: Path, req_id: str, adr_id: str, allocated_tasks: list[str]) -> list[dict]:
        protocol = ProjectProtocol(worktree)
        req = protocol.requirement(req_id)
        adr = protocol.adr(adr_id)
        self.validator.validate(req, "requirement.schema.json")
        self.validator.validate(adr, "adr.schema.json")
        if req["id"] != req_id or req.get("status") != "READY":
            raise PlanningError("Requirement must use the allocated ID and status READY")
        if adr["id"] != adr_id or adr.get("status") != "ACCEPTED" or req_id not in adr.get("requirement_ids", []):
            raise PlanningError("ADR must use the allocated ID, be ACCEPTED and reference the Requirement")

        tasks: list[dict] = []
        allocated = set(allocated_tasks)
        for path in sorted((worktree / ".agent/tasks").glob("TASK-*.yaml")):
            task = protocol.load_agent_yaml(path)
            if req_id not in task.get("requirement_ids", []):
                continue
            self.validator.validate(task, "task.schema.json")
            if task["id"] not in allocated:
                raise PlanningError(f"Planner used unallocated task ID: {task['id']}")
            if adr_id not in task.get("adr_ids", []):
                raise PlanningError(f"Task {task['id']} does not reference {adr_id}")
            if task["assigned_agent"] not in RUNTIME_AGENTS:
                raise PlanningError(f"Unsupported runtime agent: {task['assigned_agent']}")
            if task.get("status") != "PENDING":
                raise PlanningError(f"Task {task['id']} must start PENDING")
            tasks.append(task)
        if not tasks:
            raise PlanningError("Planner produced no tasks")

        ids = {task["id"] for task in tasks}
        for task in tasks:
            unknown = [dep for dep in task.get("dependencies", []) if dep not in ids]
            if unknown:
                raise PlanningError(f"Task {task['id']} has unknown dependencies: {unknown}")

        forbidden = self._forbidden_agents(req, adr)
        violations = [task["id"] for task in tasks if task["assigned_agent"] in forbidden]
        if violations:
            raise PlanningError(f"Planner reintroduced out-of-scope module in tasks: {violations}")

        checks = protocol.verification_policy().get("checks", {})
        for task in tasks:
            if task["assigned_agent"] != "reviewer" and not task.get("verification"):
                raise PlanningError(f"Task {task['id']} requires verification")
            undefined = [name for name in task.get("verification", []) if name not in checks]
            if undefined:
                raise PlanningError(f"Task {task['id']} references undefined verification: {undefined}")
        return self._topological(tasks)

    def plan(self, requirement_text: str, base_branch: str | None = None) -> PlanningResult:
        git = GitRepository(self.repo_root)
        git.ensure()
        token = _distributed_token()
        req_id = f"REQ-{token}"
        adr_id = f"ADR-{token}"
        allocated_tasks = [f"TASK-{token}-{index:02d}" for index in range(1, 21)]
        feature_worktree, feature_branch = FeatureBranchManager(git).create(req_id, base_branch)
        protocol = ProjectProtocol(feature_worktree)
        project = protocol.project()
        constitution_path = feature_worktree / ".agent/constitution.md"
        constitution = constitution_path.read_text(encoding="utf-8") if constitution_path.is_file() else ""

        req_path = f".agent/requirements/{req_id}.yaml"
        action = self._apply_planning_action(
            feature_worktree,
            "requirement",
            "REQUIREMENT",
            {
                "user_requirement": requirement_text,
                "required_id": req_id,
                "target_path": req_path,
                "project": project,
                "constitution": constitution,
                "instructions": "Create exactly one testable Requirement with status READY. Explicitly list out_of_scope and out_of_scope_modules when known.",
            },
            [req_path],
            0,
        )
        if action.status == "BLOCKED":
            raise PlanningError(action.block.question if action.block else "Requirement planning blocked")
        req = protocol.requirement(req_id)
        self.validator.validate(req, "requirement.schema.json")
        if req["id"] != req_id or req.get("status") != "READY":
            raise PlanningError("Requirement output did not honor allocated ID/status")

        adr_path = f".agent/decisions/{adr_id}.yaml"
        action = self._apply_planning_action(
            feature_worktree,
            "architect",
            "ARCHITECTURE",
            {
                "requirement": req,
                "required_id": adr_id,
                "target_path": adr_path,
                "project": project,
                "constitution": constitution,
                "instructions": "Create exactly one ACCEPTED ADR. Preserve requirement scope and explicitly mark untouched modules with change_required=false when useful.",
            },
            [adr_path],
            1,
        )
        if action.status == "BLOCKED":
            raise PlanningError(action.block.question if action.block else "Architecture planning blocked")
        adr = protocol.adr(adr_id)
        self.validator.validate(adr, "adr.schema.json")
        if req_id not in adr.get("requirement_ids", []):
            raise PlanningError("ADR does not reference generated requirement")

        task_paths = [f".agent/tasks/{task_id}.yaml" for task_id in allocated_tasks]
        action = self._apply_planning_action(
            feature_worktree,
            "planner",
            "PLANNING",
            {
                "requirement": req,
                "architecture": adr,
                "allowed_task_ids": allocated_tasks,
                "allowed_paths": task_paths,
                "available_agents": sorted(RUNTIME_AGENTS),
                "available_verification_checks": sorted(protocol.verification_policy().get("checks", {}).keys()),
                "constitution": constitution,
                "instructions": "Create the smallest acyclic Task DAG. Use only allocated IDs. Every task starts PENDING. Do not reintroduce out-of-scope modules.",
            },
            task_paths,
            2,
        )
        if action.status == "BLOCKED":
            raise PlanningError(action.block.question if action.block else "Task planning blocked")
        tasks = self._validate_plan(feature_worktree, req_id, adr_id, allocated_tasks)
        commit = GitRepository(feature_worktree).commit(f"docs(agent): plan {req_id}")
        return PlanningResult(req_id, adr_id, [task["id"] for task in tasks], feature_branch, str(feature_worktree), commit)
