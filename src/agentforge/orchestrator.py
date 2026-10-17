from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from agentforge.context import ContextBuilder
from agentforge.evidence import EvidenceIndex
from agentforge.git import FeatureBranchManager, GitRepository, WorktreeManager
from agentforge.llm.base import AgentDriver
from agentforge.policy import PolicyEngine
from agentforge.protocol.loader import ProjectProtocol
from agentforge.state_machine import TaskStateMachine
from agentforge.verification import VerificationRunner
from agentforge.workspace import WorkspaceMutator


@dataclass
class TaskRunResult:
    task_id: str
    status: str
    branch: str
    worktree: str
    context_hash: str
    changed_files: list[str]
    verification: list[dict]
    commit_sha: str | None
    summary: str
    transitions: list[str]
    block: dict | None = None


class TaskOrchestrator:
    """Control-plane execution of exactly one Task.

    The primary repository remains the Git control root. `protocol_root` may be
    a linked feature worktree containing newly planned REQ/ADR/TASK artifacts
    that have not yet reached the primary/base worktree. The model still runs
    only inside a fresh task worktree created from `base_branch`.
    """

    def __init__(self, repo_root: Path, driver: AgentDriver):
        self.repo_root = repo_root.resolve()
        self.driver = driver

    @staticmethod
    def _to_running(status: str) -> list[str]:
        transitions: list[str] = []
        current = status
        if current in {"PENDING", "FAILED", "BLOCKED"}:
            TaskStateMachine.require(current, "READY")
            transitions.append(f"{current}->READY")
            current = "READY"
        TaskStateMachine.require(current, "RUNNING")
        transitions.append(f"{current}->RUNNING")
        return transitions

    def run_task(
        self,
        task_id: str,
        base_branch: str | None = None,
        protocol_root: Path | None = None,
    ) -> TaskRunResult:
        source_root = (protocol_root or self.repo_root).resolve()
        source_git = GitRepository(source_root)
        source_git.ensure()
        if base_branch is not None and source_git.current_branch() != base_branch:
            raise ValueError(
                f"Protocol source branch mismatch: expected {base_branch}, "
                f"got {source_git.current_branch()}"
            )

        source_protocol = ProjectProtocol(source_root)
        source_task = source_protocol.task(task_id)
        if source_task.get("status") not in {"PENDING", "READY", "FAILED", "BLOCKED"}:
            raise ValueError(f"Task is not runnable from state {source_task.get('status')}")
        transitions = self._to_running(source_task["status"])

        git = GitRepository(self.repo_root)
        git.ensure()
        worktree, branch = WorktreeManager(git).create(task_id, base_branch=base_branch)
        protocol = ProjectProtocol(worktree)
        task = protocol.task(task_id)
        agent = protocol.agent_definition(task["assigned_agent"])
        context = ContextBuilder(worktree).build(task_id)
        action = self.driver.execute(ContextBuilder.to_prompt(context), context)

        if action.status == "BLOCKED":
            TaskStateMachine.require("RUNNING", "BLOCKED")
            transitions.append("RUNNING->BLOCKED")
            return TaskRunResult(
                task_id, "BLOCKED", branch, str(worktree), context["context_hash"],
                [], [], None, action.summary, transitions,
                action.block.model_dump() if action.block else None,
            )

        EvidenceIndex(worktree).build().require(action.evidence, minimum=1)
        policy = PolicyEngine(task, agent)
        WorkspaceMutator(worktree, policy).apply(action)
        changed = GitRepository(worktree).changed_files()
        for path in changed:
            policy.require_write(path)

        TaskStateMachine.require("RUNNING", "VERIFYING")
        transitions.append("RUNNING->VERIFYING")
        verification = VerificationRunner(worktree, protocol.verification_policy()).run(task.get("verification", []))
        TaskStateMachine.require("VERIFYING", "DONE")
        transitions.append("VERIFYING->DONE")

        sha: str | None = None
        if changed:
            message = f"feat(agent): complete {task_id}\n\nTASK: {task_id}"
            for req in task.get("requirement_ids", []):
                message += f"\nREQ: {req}"
            sha = GitRepository(worktree).commit(message)

        return TaskRunResult(
            task_id, "DONE", branch, str(worktree), context["context_hash"],
            changed, verification, sha, action.summary, transitions,
        )


@dataclass
class FeatureTaskResult:
    feature_id: str
    feature_branch: str
    feature_worktree: str
    task: TaskRunResult
    integration_sha: str | None


class FeatureOrchestrator:
    """Serially integrate verified task commits into a feature branch."""

    def __init__(self, repo_root: Path, driver: AgentDriver):
        self.repo_root = repo_root.resolve()
        self.driver = driver
        self.git = GitRepository(self.repo_root)

    def run_task(self, feature_id: str, task_id: str, base_branch: str | None = None) -> FeatureTaskResult:
        feature_worktree, feature_branch = FeatureBranchManager(self.git).create(feature_id, base_branch)
        task_result = TaskOrchestrator(self.repo_root, self.driver).run_task(
            task_id,
            base_branch=feature_branch,
            protocol_root=feature_worktree,
        )
        integration_sha = None
        if task_result.status == "DONE" and task_result.commit_sha:
            integration_sha = FeatureBranchManager(self.git).merge_task(
                feature_worktree, task_result.branch, task_id
            )
        return FeatureTaskResult(
            feature_id, feature_branch, str(feature_worktree), task_result, integration_sha
        )
