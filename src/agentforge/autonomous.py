from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agentforge.coding import CodingResult, LiveCodingRuntime, VerificationSpec
from agentforge.contracts import ArchitectureDraft, RequirementDraft, TaskBundle, TaskDraft
from agentforge.evidence import EvidenceIndex
from agentforge.live import LivePlanningPipeline
from agentforge.llm import OpenAICompatibleClient


class AgentExecutionProfile(BaseModel):
    context_paths: list[str] = Field(default_factory=list)
    verification: list[VerificationSpec] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    status: Literal["APPROVE", "REQUEST_CHANGES", "BLOCKED"]
    summary: str
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_review(self):
        if self.status == "APPROVE" and not self.evidence:
            raise ValueError("APPROVE requires evidence")
        return self


class TaskRunRecord(BaseModel):
    task_id: str
    agent: str
    status: Literal["SUCCESS", "BLOCKED", "FAILED"]
    attempts: int
    commit: str | None = None
    message: str = ""


class AutonomousResult(BaseModel):
    status: Literal["PR_READY", "SUCCESS", "BLOCKED", "FAILED", "REVIEW_CHANGES"]
    requirement_id: str
    adr_id: str
    feature_branch: str
    task_runs: list[TaskRunRecord] = Field(default_factory=list)
    review: ReviewDecision | None = None
    pr_url: str | None = None
    message: str = ""


class GitWorkspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.root,
            shell=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if check and completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
        return completed

    def ensure_clean(self) -> None:
        if self._run("status", "--porcelain").stdout.strip():
            raise RuntimeError("Repository must be clean before autonomous execution")

    @staticmethod
    def validate_branch_name(branch: str) -> None:
        if (
            not re.fullmatch(r"feature/[A-Za-z0-9._/-]+", branch)
            or ".." in branch
            or branch.endswith("/")
            or "//" in branch
        ):
            raise ValueError(f"Unsafe feature branch name: {branch}")

    def create_feature_branch(self, branch: str, base_branch: str) -> None:
        self.validate_branch_name(branch)
        self._run("switch", "-c", branch, base_branch)

    def has_changes(self) -> bool:
        return bool(self._run("status", "--porcelain").stdout.strip())

    def commit_all(self, message: str) -> str:
        if not self.has_changes():
            raise RuntimeError("Task reported success but produced no repository changes")
        self._run("add", "-A")
        self._run("commit", "-m", message)
        return self._run("rev-parse", "HEAD").stdout.strip()

    def diff_from(self, base_branch: str, max_chars: int = 40000) -> str:
        diff = self._run("diff", f"{base_branch}...HEAD", "--").stdout
        return diff[-max_chars:]

    def push(self, remote: str, branch: str) -> None:
        self.validate_branch_name(branch)
        self._run("push", "-u", remote, branch)


class GitHubPullRequestPublisher:
    def __init__(
        self,
        repo_full_name: str,
        token: str,
        api_base: str = "https://api.github.com",
        timeout: float = 30.0,
    ):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_full_name):
            raise ValueError("Invalid GitHub repository name")
        self.repo_full_name = repo_full_name
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> str:
        payload = json.dumps(
            {
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "draft": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base}/repos/{self.repo_full_name}/pulls",
            data=payload,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GitHub PR request failed: {exc}") from exc
        url = data.get("html_url")
        if not isinstance(url, str) or not url:
            raise RuntimeError("GitHub PR response missing html_url")
        return url


class ProtocolWriter:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()

    @staticmethod
    def _write_json_yaml(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write(self, requirement: RequirementDraft, architecture: ArchitectureDraft, tasks: TaskBundle) -> None:
        self._write_json_yaml(
            self.repo_root / ".agent/requirements" / f"{requirement.id}.yaml",
            requirement.model_dump(),
        )
        self._write_json_yaml(
            self.repo_root / ".agent/decisions" / f"{architecture.id}.yaml",
            architecture.model_dump(),
        )
        for task in tasks.tasks:
            self._write_json_yaml(
                self.repo_root / ".agent/tasks" / f"{task.id}.yaml",
                task.model_dump(),
            )


def topological_tasks(bundle: TaskBundle) -> list[TaskDraft]:
    by_id = {task.id: task for task in bundle.tasks}
    indegree = {task.id: 0 for task in bundle.tasks}
    followers: dict[str, list[str]] = {task.id: [] for task in bundle.tasks}
    for task in bundle.tasks:
        for dependency in task.dependencies:
            if dependency not in by_id:
                raise ValueError(f"{task.id} has unknown dependency {dependency}")
            indegree[task.id] += 1
            followers[dependency].append(task.id)

    ready = [task.id for task in bundle.tasks if indegree[task.id] == 0]
    ordered: list[TaskDraft] = []
    while ready:
        current = ready.pop(0)
        ordered.append(by_id[current])
        for follower in followers[current]:
            indegree[follower] -= 1
            if indegree[follower] == 0:
                ready.append(follower)
    if len(ordered) != len(bundle.tasks):
        raise ValueError("Task DAG contains a cycle")
    return ordered


class AutonomousDevelopmentPipeline:
    def __init__(
        self,
        *,
        client: OpenAICompatibleClient,
        repo_root: Path,
        profiles: dict[str, AgentExecutionProfile],
        allowed_verification_executables: set[str],
        max_coding_attempts: int = 2,
    ):
        self.client = client
        self.repo_root = repo_root.resolve()
        self.profiles = profiles
        self.allowed_verification_executables = set(allowed_verification_executables)
        self.max_coding_attempts = max_coding_attempts

    def run(
        self,
        request: str,
        *,
        base_branch: str = "main",
        requirement_id: str = "REQ-900001",
        adr_id: str = "ADR-900001",
        feature_branch: str | None = None,
        push: bool = False,
        remote: str = "origin",
        publisher: GitHubPullRequestPublisher | None = None,
        create_pr: bool = False,
    ) -> AutonomousResult:
        if create_pr and not push:
            raise ValueError("create_pr requires push=True so the remote branch exists")
        if create_pr and publisher is None:
            raise ValueError("create_pr requires a publisher")

        git = GitWorkspace(self.repo_root)
        git.ensure_clean()

        plan = LivePlanningPipeline(self.client).plan(request, requirement_id, adr_id)
        ordered_tasks = topological_tasks(plan.tasks)
        for task in ordered_tasks:
            if task.assigned_agent not in self.profiles:
                raise ValueError(f"No execution profile for agent {task.assigned_agent}")

        branch = feature_branch or f"feature/{plan.requirement.id}"
        git.create_feature_branch(branch, base_branch)

        ProtocolWriter(self.repo_root).write(plan.requirement, plan.architecture, plan.tasks)
        git.commit_all(f"chore(agentforge): record {plan.requirement.id} plan")

        task_runs: list[TaskRunRecord] = []
        for task in ordered_tasks:
            profile = self.profiles[task.assigned_agent]
            runtime = LiveCodingRuntime(
                self.client,
                self.repo_root,
                self.allowed_verification_executables,
                max_attempts=self.max_coding_attempts,
            )
            result: CodingResult = runtime.execute(
                task,
                context_paths=profile.context_paths,
                verification=profile.verification,
            )
            record = TaskRunRecord(
                task_id=task.id,
                agent=task.assigned_agent,
                status=result.status,
                attempts=result.attempts,
                message=result.message,
            )
            if result.status != "SUCCESS":
                task_runs.append(record)
                return AutonomousResult(
                    status="BLOCKED" if result.status == "BLOCKED" else "FAILED",
                    requirement_id=plan.requirement.id,
                    adr_id=plan.architecture.id,
                    feature_branch=branch,
                    task_runs=task_runs,
                    message=f"{task.id} did not complete successfully",
                )
            record.commit = git.commit_all(f"feat({task.assigned_agent}): complete {task.id}")
            task_runs.append(record)

        diff = git.diff_from(base_branch)
        review = self.client.complete_model(
            system=(
                "You are the read-only AgentForge reviewer. Return JSON only. "
                "Do not propose file writes. APPROVE only if the diff is within the requirement/ADR/task scope "
                "and all task verification passed."
            ),
            user=(
                f"REQUIREMENT:\n{plan.requirement.model_dump_json()}\n\n"
                f"ARCHITECTURE:\n{plan.architecture.model_dump_json()}\n\n"
                f"TASKS:\n{plan.tasks.model_dump_json()}\n\n"
                f"DIFF:\n{diff}"
            ),
            schema=ReviewDecision,
        )
        EvidenceIndex(self.repo_root).build().require(review.evidence)
        if review.status != "APPROVE":
            return AutonomousResult(
                status="BLOCKED" if review.status == "BLOCKED" else "REVIEW_CHANGES",
                requirement_id=plan.requirement.id,
                adr_id=plan.architecture.id,
                feature_branch=branch,
                task_runs=task_runs,
                review=review,
                message=review.summary,
            )

        if push:
            git.push(remote, branch)

        pr_url: str | None = None
        if create_pr and publisher is not None:
            pr_url = publisher.create_pull_request(
                title=f"{plan.requirement.id}: {plan.requirement.title}",
                body=(
                    f"Requirement: {plan.requirement.id}\n"
                    f"Architecture: {plan.architecture.id}\n"
                    f"Tasks: {', '.join(task.id for task in ordered_tasks)}\n\n"
                    f"Reviewer: APPROVE\n{review.summary}"
                ),
                head=branch,
                base=base_branch,
            )

        return AutonomousResult(
            status="PR_READY" if pr_url else "SUCCESS",
            requirement_id=plan.requirement.id,
            adr_id=plan.architecture.id,
            feature_branch=branch,
            task_runs=task_runs,
            review=review,
            pr_url=pr_url,
            message="Autonomous pipeline completed; merge remains a human decision.",
        )
