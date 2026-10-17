from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import json

from agentforge.delivery import FeatureDeliveryService
from agentforge.git import FeatureBranchManager, GitRepository
from agentforge.llm.base import AgentDriver
from agentforge.orchestrator import TaskOrchestrator
from agentforge.planning import FeaturePlanningPipeline
from agentforge.protocol.loader import ProjectProtocol
from agentforge.util import dump_yaml
from agentforge.verification import VerificationRunner


@dataclass
class LiveFeatureResult:
    status: str
    requirement_id: str
    adr_id: str
    feature_branch: str
    feature_worktree: str
    task_results: list[dict[str, Any]]
    handoff_ids: list[str]
    final_verification: list[dict[str, Any]]
    pull_request: dict[str, Any] | None = None
    block: dict[str, Any] | None = None


class LiveFeaturePipeline:
    """REQ -> ADR -> Task DAG -> isolated task execution -> feature integration.

    This pipeline stops at PR delivery. It has no merge-to-main path and writes
    no long-term memory; those operations belong to an explicit post-merge flow.
    """

    def __init__(self, repo_root: Path, driver: AgentDriver):
        self.repo_root = repo_root.resolve()
        self.driver = driver
        self.git = GitRepository(self.repo_root)

    @staticmethod
    def _handoff_id(requirement_id: str, index: int) -> str:
        token = requirement_id.removeprefix("REQ-")
        return f"HO-{token}-{index:02d}"

    @staticmethod
    def _next_tasks(tasks: list[dict], task_id: str) -> list[str]:
        return [task["id"] for task in tasks if task_id in task.get("dependencies", [])]

    def _write_task_done_and_handoff(
        self,
        feature_worktree: Path,
        requirement_id: str,
        task: dict,
        result,
        index: int,
        tasks: list[dict],
    ) -> str:
        protocol = ProjectProtocol(feature_worktree)
        current = protocol.task(task["id"])
        current["status"] = "DONE"
        dump_yaml(feature_worktree / ".agent" / "tasks" / f"{task['id']}.yaml", current)
        handoff_id = self._handoff_id(requirement_id, index)
        payload = {
            "handoff_id": handoff_id,
            "task_id": task["id"],
            "source_agent": task["assigned_agent"],
            "changed_files": result.changed_files,
            "contracts_created_or_changed": [],
            "tests": {"state": "PASS", "verification": result.verification},
            "warnings": [],
            "next_tasks": self._next_tasks(tasks, task["id"]),
            "evidence": [task["id"], *task.get("requirement_ids", []), *task.get("adr_ids", [])],
        }
        dump_yaml(feature_worktree / ".agent" / "handoffs" / f"{handoff_id}.yaml", payload)
        GitRepository(feature_worktree).commit(f"chore(agent): finish {task['id']} and {handoff_id}")
        return handoff_id

    def run(
        self,
        requirement_text: str,
        *,
        base_branch: str | None = None,
        delivery: FeatureDeliveryService | None = None,
        create_pr: bool = False,
        push: bool = False,
        draft_pr: bool = False,
    ) -> LiveFeatureResult:
        planning = FeaturePlanningPipeline(self.repo_root, self.driver).plan(requirement_text, base_branch=base_branch)
        feature_worktree = Path(planning.feature_worktree)
        feature_branch = planning.feature_branch
        protocol = ProjectProtocol(feature_worktree)
        tasks = [protocol.task(task_id) for task_id in planning.task_ids]
        manager = FeatureBranchManager(self.git)

        task_results: list[dict[str, Any]] = []
        handoff_ids: list[str] = []
        for index, task in enumerate(tasks, start=1):
            result = TaskOrchestrator(self.repo_root, self.driver).run_task(
                task["id"],
                base_branch=feature_branch,
                protocol_root=feature_worktree,
            )
            task_results.append(asdict(result))
            if result.status == "BLOCKED":
                current = ProjectProtocol(feature_worktree).task(task["id"])
                current["status"] = "BLOCKED"
                dump_yaml(feature_worktree / ".agent" / "tasks" / f"{task['id']}.yaml", current)
                GitRepository(feature_worktree).commit(f"chore(agent): block {task['id']}")
                return LiveFeatureResult(
                    "BLOCKED", planning.requirement_id, planning.adr_id, feature_branch,
                    str(feature_worktree), task_results, handoff_ids, [], None, result.block,
                )
            if result.commit_sha:
                manager.merge_task(feature_worktree, result.branch, task["id"])
            handoff_ids.append(
                self._write_task_done_and_handoff(
                    feature_worktree, planning.requirement_id, task, result, index, tasks
                )
            )

        verification_names: list[str] = []
        for task in tasks:
            for name in task.get("verification", []):
                if name not in verification_names:
                    verification_names.append(name)
        final_verification = VerificationRunner(
            feature_worktree,
            ProjectProtocol(feature_worktree).verification_policy(),
        ).run(verification_names)

        state_path = feature_worktree / ".agent" / "state" / "project-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "project_id": protocol.project()["project"]["id"],
            "workflow_state": "PR_READY",
            "active_requirement": planning.requirement_id,
            "active_tasks": [],
            "completed_tasks": planning.task_ids,
            "blocked_tasks": [],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        GitRepository(feature_worktree).commit(f"chore(agent): mark {planning.requirement_id} PR_READY")

        pr = None
        if create_pr:
            if delivery is None:
                raise ValueError("create_pr=True requires FeatureDeliveryService")
            req = ProjectProtocol(feature_worktree).requirement(planning.requirement_id)
            body = (
                f"Requirement: {planning.requirement_id}\n"
                f"Architecture: {planning.adr_id}\n"
                f"Tasks: {', '.join(planning.task_ids)}\n"
                "Generated by AgentForge constrained live feature pipeline.\n"
            )
            delivered = delivery.deliver(
                feature_branch,
                f"{planning.requirement_id}: {req['title']}",
                body,
                push=push,
                draft=draft_pr,
            )
            pr = delivered.pull_request

        return LiveFeatureResult(
            "PR_OPEN" if pr else "PR_READY",
            planning.requirement_id,
            planning.adr_id,
            feature_branch,
            str(feature_worktree),
            task_results,
            handoff_ids,
            final_verification,
            pr,
        )
