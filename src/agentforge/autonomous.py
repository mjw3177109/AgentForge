from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agentforge.coding import CodingResult, LiveCodingRuntime, VerificationSpec
from agentforge.repair_v3 import SafeRepairRuntime
from agentforge.contracts import ArchitectureDraft, RequirementDraft, TaskBundle, TaskDraft
from agentforge.evidence import EvidenceIndex
from agentforge.errors import EvidenceError, PolicyDenied
from agentforge.live import LivePlanningPipeline
from agentforge.llm import OpenAICompatibleClient
from agentforge.policy import PolicyEngine, norm


_EVIDENCE_ID_RE = re.compile(r"^(REQ|ADR|TASK|FACT|API|DB|RULE|SEC|MEM)-[A-Za-z0-9._:-]+$")


class AgentExecutionProfile(BaseModel):
    context_paths: list[str] = Field(default_factory=list)
    verification: list[VerificationSpec] = Field(default_factory=list)
    read_scope: list[str] = Field(default_factory=list)
    write_scope: list[str] = Field(default_factory=list)
    deny_scope: list[str] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    status: Literal["APPROVE", "REQUEST_CHANGES", "BLOCKED"]
    summary: str
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_review(self):
        invalid = [item for item in self.evidence if not _EVIDENCE_ID_RE.fullmatch(item)]
        if invalid:
            raise ValueError("Reviewer evidence must contain repository evidence IDs, never prose or file paths")
        if self.status == "APPROVE" and not self.evidence:
            raise ValueError("APPROVE requires evidence")
        if self.status == "REQUEST_CHANGES" and not any(item.startswith("TASK-") for item in self.evidence):
            raise ValueError("REQUEST_CHANGES requires at least one affected TASK evidence id")
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
        max_review_rounds: int = 2,
        enable_v3_safe_repair: bool = False,
    ):
        self.client = client
        self.repo_root = repo_root.resolve()
        self.profiles = profiles
        self.allowed_verification_executables = set(allowed_verification_executables)
        self.max_coding_attempts = max_coding_attempts
        self.max_review_rounds = max_review_rounds
        self.enable_v3_safe_repair = enable_v3_safe_repair

    def _project_context(self) -> str:
        path = self.repo_root / ".agent/project.yaml"
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:20000]

    def _review_context(self, max_chars: int = 40000) -> str:
        """Build a read-only reviewer bundle from declared verified repository context."""
        candidates: list[str] = [".agent/project.yaml"]
        contracts_dir = self.repo_root / ".agent/contracts"
        if contracts_dir.is_dir():
            for path in sorted(contracts_dir.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    candidates.append(path.relative_to(self.repo_root).as_posix())
        for profile in self.profiles.values():
            candidates.extend(profile.context_paths)

        chunks: list[str] = []
        seen: set[str] = set()
        used = 0
        for raw in candidates:
            rel = str(raw).replace("\\", "/").strip()
            if not rel or rel in seen or any(char in rel for char in "*?["):
                continue
            seen.add(rel)
            path = (self.repo_root / rel).resolve()
            try:
                path.relative_to(self.repo_root)
            except ValueError:
                continue
            if not path.is_file() or path.is_symlink():
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            block = f"--- {rel} ---\n{body}\n"
            remaining = max_chars - used
            if remaining <= 0:
                break
            if len(block) > remaining:
                block = block[:remaining]
            chunks.append(block)
            used += len(block)
        return "\n".join(chunks)

    def _task_constraints(self) -> str:
        payload: dict[str, dict[str, list[str]]] = {}
        for name, profile in sorted(self.profiles.items()):
            payload[name] = {
                "read_scope": profile.read_scope,
                "write_scope": profile.write_scope,
                "deny_scope": profile.deny_scope,
            }
        return (
            "assigned_agent MUST be one of the exact profile names below. "
            "Prefer exactly one task per needed execution agent so each task can pass that agent's complete verification gate. "
            "For read_scope/write_scope, a task may use an exact profile glob or a concrete repository path contained by that glob, "
            "but MUST NOT invent a broader or different glob. Profile deny_scope entries are mandatory and may only be supplemented. "
            "Do not use semantic scope labels.\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

    @staticmethod
    def _scope_entry_within_ceiling(entry: str, ceilings: list[str]) -> bool:
        if entry in ceilings:
            return True

        if any(char in entry for char in "*?["):
            # A planner may narrow a profile's / ** tree ceiling to a deeper
            # / ** tree (e.g. server/src/main/** -> server/src/main/java/**).
            # Only trailing recursive directory globs are provably contained.
            # Arbitrary patterns, traversal segments, and sibling trees remain
            # denied rather than being assumed safe.
            if not entry.endswith("/**") or entry.count("*") != 2:
                return False
            root = entry[:-3]
            if not root or any(seg in {"", ".", ".."} for seg in root.split("/")):
                return False
            if any(char in root for char in "*?[\\"):
                return False
            for ceiling in ceilings:
                if not ceiling.endswith("/**") or ceiling.count("*") != 2:
                    continue
                base = ceiling[:-3]
                if not base or any(seg in {"", ".", ".."} for seg in base.split("/")):
                    continue
                if any(char in base for char in "*?[\\"):
                    continue
                if root == base or root.startswith(base + "/"):
                    return True
            return False

        return any(fnmatchcase(entry, ceiling) for ceiling in ceilings)

    @classmethod
    def _validate_task_profile_scope(cls, task: TaskDraft, profile: AgentExecutionProfile) -> None:
        for field_name, task_values, allowed_values in (
            ("read", task.scope.read, profile.read_scope),
            ("write", task.scope.write, profile.write_scope),
        ):
            if allowed_values:
                extras = sorted(
                    value for value in task_values
                    if not cls._scope_entry_within_ceiling(value, allowed_values)
                )
                if extras:
                    raise ValueError(
                        f"{task.id} expanded {field_name} scope beyond execution profile: {extras}"
                    )
        if profile.write_scope and not task.scope.write:
            raise ValueError(f"{task.id} has no write scope although its execution profile is writable")

        for context_path in profile.context_paths:
            if profile.read_scope and not cls._scope_entry_within_ceiling(context_path, profile.read_scope):
                raise ValueError(
                    f"Execution profile context path is outside its own read ceiling: {context_path}"
                )
            if context_path not in task.scope.read:
                task.scope.read.append(context_path)

        for denied in profile.deny_scope:
            if denied not in task.scope.deny:
                task.scope.deny.append(denied)

        policy = PolicyEngine(read=task.scope.read, write=task.scope.write, deny=task.scope.deny)
        for context_path in profile.context_paths:
            policy.require_read(context_path)

    def _repair_context_paths(self, task: TaskDraft, profile: AgentExecutionProfile) -> list[str]:
        paths = list(profile.context_paths)
        policy = PolicyEngine(read=task.scope.read, write=task.scope.write, deny=task.scope.deny)
        candidates: set[str] = set()
        for raw in task.scope.write:
            clean = str(raw).replace("\\", "/").strip()
            if clean.endswith("/"):
                root = self.repo_root / norm(clean)
                if root.is_dir():
                    for path in root.rglob("*"):
                        if path.is_file() and not path.is_symlink():
                            candidates.add(path.relative_to(self.repo_root).as_posix())
            elif any(char in clean for char in "*?["):
                for path in self.repo_root.glob(clean):
                    if path.is_file() and not path.is_symlink():
                        candidates.add(path.relative_to(self.repo_root).as_posix())
            else:
                path = self.repo_root / norm(clean)
                if path.is_file() and not path.is_symlink():
                    candidates.add(path.relative_to(self.repo_root).as_posix())

        for rel in sorted(candidates):
            try:
                policy.require_read(rel)
            except PolicyDenied:
                continue
            if rel not in paths:
                paths.append(rel)
            if len(paths) >= 40:
                break
        return paths

    def _review(
        self,
        *,
        plan,
        task_runs: list[TaskRunRecord],
        base_branch: str,
        git: GitWorkspace,
    ) -> ReviewDecision:
        evidence_index = EvidenceIndex(self.repo_root).build()
        evidence_ids = sorted(evidence_index.ids)
        # The reviewer can ask for repairs only in a TASK's actual write scope.
        # Immutable verification fixtures are maintainer-owned, not writable
        # by any agent unless a separate, explicitly authorized task exists.
        task_write_scopes = {
            task.id: {"agent": task.assigned_agent, "write": task.scope.write}
            for task in plan.tasks.tasks
        }
        prompt = (
            f"REQUIREMENT:\n{plan.requirement.model_dump_json()}\n\n"
            f"ARCHITECTURE:\n{plan.architecture.model_dump_json()}\n\n"
            f"TASKS:\n{plan.tasks.model_dump_json()}\n\n"
            f"TASK RUNS (orchestrator-recorded verification status):\n"
            f"{json.dumps([record.model_dump() for record in task_runs], ensure_ascii=False, indent=2)}\n\n"
            f"VERIFIED REVIEW CONTEXT (project facts, contracts, and declared agent context):\n{self._review_context()}\n\n"
            f"AUTHORIZED TASK WRITE SCOPES:\n{json.dumps(task_write_scopes, ensure_ascii=False)}\n\n"
            "AVAILABLE EVIDENCE IDS:\n"
            f"{json.dumps(evidence_ids, ensure_ascii=False)}\n\n"
            "Put all criticism and requested changes in summary. evidence must contain ONLY exact IDs from AVAILABLE EVIDENCE IDS. "
            "For REQUEST_CHANGES, include every affected TASK id in evidence so the orchestrator can route repairs. "
            "Evaluate all currently identifiable material defects across all tasks in this review; do not intentionally defer known defects to later review cycles. "
            "Requested changes must stay within the requirement, ADR, VERIFIED contracts, and VERIFIED project context; do not invent endpoints, identity sources, or integration facts. "
            "REQUEST_CHANGES has a strict burden of proof: every requested change must be directly supported by REQUIREMENT, ARCHITECTURE, VERIFIED REVIEW CONTEXT, TASK RUNS, or DIFF. "
            "Do not use hypothetical or conditional concerns (for example may, might, could, if, perhaps, possibly) as rejection reasons. "
            "Do not require an 'existing' integration, auth client, privileged scope, event handler, endpoint, or other project component unless it is explicitly present in VERIFIED REVIEW CONTEXT or DIFF. "
            "When a VERIFIED contract defines an internal service seam for a trusted external flow but VERIFIED REVIEW CONTEXT contains no integration component, review the seam itself and do not invent an integration target. "
            "When a VERIFIED contract names the endpoint or scope a consumer must use, do not infer a broader privileged endpoint or scope that the contract does not define. "
            "Tests and verification fixtures are maintainer-owned acceptance evidence. Do not request that a coding TASK create, overwrite, or edit a test file outside its AUTHORIZED TASK WRITE SCOPES. "
            "When you find a concrete production behavior defect, describe its observable failure and request a change in the affected TASK's authorized production files; do not require a new test file as the only repair. "
            "If a critical property cannot be established solely because additional independent verification is needed and no TASK owns those verification paths, use BLOCKED and identify the missing independent test, rather than routing an impossible REQUEST_CHANGES repair or inventing permission. "
            "Never treat incomplete test coverage as evidence that a known behavioral defect is acceptable. "
            "Do not use file paths or prose in evidence. Existing unchanged files may not appear in DIFF; use VERIFIED REVIEW CONTEXT before claiming an unchanged project component is absent.\n\n"
            f"DIFF:\n{git.diff_from(base_branch)}"
        )
        for attempt in range(2):
            review = self.client.complete_model(
                system=(
                    "You are the read-only AgentForge reviewer. Return JSON only. "
                    "Do not propose file writes. APPROVE only if the diff is within the requirement/ADR/task scope, "
                    "cross-stack contracts are consistent, security/business rules are preserved, and all task verification passed. "
                    "REQUEST_CHANGES must be routed through affected TASK evidence IDs."
                ),
                user=prompt,
                schema=ReviewDecision,
            )
            try:
                evidence_index.require(review.evidence)
                return review
            except EvidenceError as exc:
                if attempt == 0:
                    prompt += (
                        "\n\nThe previous reviewer output used unknown evidence. Correct only the evidence field using exact AVAILABLE EVIDENCE IDS. "
                        f"Validation error: {exc}"
                    )
                    continue
                raise
        raise RuntimeError("Reviewer did not return valid evidence")

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

        plan = LivePlanningPipeline(self.client).plan(
            request,
            requirement_id,
            adr_id,
            project_context=self._project_context(),
            task_constraints=self._task_constraints(),
        )
        ordered_tasks = topological_tasks(plan.tasks)
        task_by_id = {task.id: task for task in ordered_tasks}
        for task in ordered_tasks:
            if task.assigned_agent not in self.profiles:
                raise ValueError(f"No execution profile for agent {task.assigned_agent}")
            self._validate_task_profile_scope(task, self.profiles[task.assigned_agent])

        branch = feature_branch or f"feature/{plan.requirement.id}"
        git.create_feature_branch(branch, base_branch)

        ProtocolWriter(self.repo_root).write(plan.requirement, plan.architecture, plan.tasks)
        git.commit_all(f"chore(agentforge): record {plan.requirement.id} plan")

        task_runs: list[TaskRunRecord] = []
        for task in ordered_tasks:
            profile = self.profiles[task.assigned_agent]
            runtime = (SafeRepairRuntime if self.enable_v3_safe_repair else LiveCodingRuntime)(
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

        review: ReviewDecision | None = None
        review_cycle = 0
        repair_counts = {task.id: 0 for task in ordered_tasks}
        while True:
            review = self._review(
                plan=plan,
                task_runs=task_runs,
                base_branch=base_branch,
                git=git,
            )
            if review.status == "APPROVE":
                break
            if review.status == "BLOCKED":
                return AutonomousResult(
                    status="BLOCKED",
                    requirement_id=plan.requirement.id,
                    adr_id=plan.architecture.id,
                    feature_branch=branch,
                    task_runs=task_runs,
                    review=review,
                    message=review.summary,
                )
            affected_ids = [item for item in review.evidence if item.startswith("TASK-")]
            if not affected_ids:
                return AutonomousResult(
                    status="REVIEW_CHANGES",
                    requirement_id=plan.requirement.id,
                    adr_id=plan.architecture.id,
                    feature_branch=branch,
                    task_runs=task_runs,
                    review=review,
                    message="Reviewer requested changes without routable TASK evidence.",
                )

            repairable_ids = [
                task_id
                for task_id in affected_ids
                if task_id in task_by_id and repair_counts[task_id] < self.max_review_rounds
            ]
            if not repairable_ids:
                return AutonomousResult(
                    status="REVIEW_CHANGES",
                    requirement_id=plan.requirement.id,
                    adr_id=plan.architecture.id,
                    feature_branch=branch,
                    task_runs=task_runs,
                    review=review,
                    message=(
                        "Reviewer still requests changes after all affected tasks exhausted "
                        f"their per-task repair budget: {review.summary}"
                    ),
                )

            for task in ordered_tasks:
                if task.id not in repairable_ids:
                    continue
                repair_attempt = repair_counts[task.id] + 1
                profile = self.profiles[task.assigned_agent]
                runtime = (SafeRepairRuntime if self.enable_v3_safe_repair else LiveCodingRuntime)(
                    self.client,
                    self.repo_root,
                    self.allowed_verification_executables,
                    max_attempts=self.max_coding_attempts,
                )
                result = runtime.execute(
                    task,
                    context_paths=self._repair_context_paths(task, profile),
                    verification=profile.verification,
                    initial_feedback=(
                        f"READ-ONLY REVIEWER REQUESTED CHANGES IN REVIEW CYCLE {review_cycle + 1}; "
                        f"TASK REPAIR ATTEMPT {repair_attempt}/{self.max_review_rounds}:\n"
                        f"{review.summary}\n\n"
                        f"Repair only {task.id}. Do not change files outside this task's scope. "
                        f"Act only on concrete reviewer findings that explicitly apply to {task.id}; ignore findings that name only other TASK ids. "
                        "REQUIREMENT, ARCHITECTURE, VERIFIED contracts, and your readable VERIFIED project context outrank reviewer prose. "
                        "Do not invent or assume missing integration, auth, client, endpoint, event, or privileged-scope components. "
                        "If reviewer prose depends on a project component absent from your readable verified context, do not fabricate that component; fix the supported in-scope findings instead. "
                        "Do not attempt to create or change tests outside this TASK's authorized write scope. If the only remaining concern is independent test coverage, say which maintainer-owned check is missing instead of widening permissions."
                    ),
                )
                record = TaskRunRecord(
                    task_id=task.id,
                    agent=task.assigned_agent,
                    status=result.status,
                    attempts=result.attempts,
                    message=(
                        f"review repair round {review_cycle + 1}, task attempt "
                        f"{repair_attempt}/{self.max_review_rounds}: {result.message}"
                    ),
                )
                if result.status != "SUCCESS":
                    task_runs.append(record)
                    return AutonomousResult(
                        status="BLOCKED" if result.status == "BLOCKED" else "FAILED",
                        requirement_id=plan.requirement.id,
                        adr_id=plan.architecture.id,
                        feature_branch=branch,
                        task_runs=task_runs,
                        review=review,
                        message=f"Reviewer repair for {task.id} did not complete successfully",
                    )
                if not git.has_changes():
                    task_runs.append(record)
                    return AutonomousResult(
                        status="REVIEW_CHANGES",
                        requirement_id=plan.requirement.id,
                        adr_id=plan.architecture.id,
                        feature_branch=branch,
                        task_runs=task_runs,
                        review=review,
                        message=f"Reviewer requested changes for {task.id}, but repair produced no repository diff.",
                    )
                record.commit = git.commit_all(
                    f"fix({task.assigned_agent}): review repair {task.id} attempt {repair_attempt}"
                )
                task_runs.append(record)
                repair_counts[task.id] = repair_attempt

            review_cycle += 1

        if review is None or review.status != "APPROVE":
            raise RuntimeError("Autonomous review loop ended without a decision")

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