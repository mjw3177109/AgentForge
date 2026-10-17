from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import shutil
import yaml

from agentforge.delivery import FeatureDeliveryService
from agentforge.errors import MemorySyncError
from agentforge.git import GitRepository
from agentforge.protocol.loader import ProjectProtocol
from agentforge.util import dump_yaml


@dataclass
class MemorySyncResult:
    requirement_id: str
    memory_id: str
    branch: str
    worktree: str
    commit_sha: str
    memory_path: str
    fact_path: str
    pull_request: dict[str, Any] | None = None


class MemoryBranchManager:
    def __init__(self, repo: GitRepository, root: Path | None = None):
        self.repo = repo
        self.root = (root or repo.root.parent / ".agentforge-memory").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def branch_name(requirement_id: str) -> str:
        return f"memory/{requirement_id.lower()}"

    def create(self, requirement_id: str, default_branch: str) -> tuple[Path, str]:
        branch = self.branch_name(requirement_id)
        path = self.root / requirement_id
        self.repo._run("worktree", "remove", "--force", str(path), check=False)
        if path.exists():
            shutil.rmtree(path)
        self.repo._run("worktree", "prune", check=False)
        # A retry deterministically rebuilds the local memory branch from the
        # current default branch. Remote updates are never force-pushed here.
        self.repo._run("branch", "-D", branch, check=False)
        self.repo._run("worktree", "add", "-b", branch, str(path), default_branch)
        return path, branch


class PostMergeMemoryService:
    """Create reviewable project memory only from facts already merged to default.

    No LLM is used here: the first memory layer is deterministic and source
    preserving. It writes to a dedicated memory branch, never directly to the
    default branch. A later explicit PR can carry the memory update into main.
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.git = GitRepository(self.repo_root)
        self.git.ensure()

    @staticmethod
    def _related_yaml(root: Path, directory: str, requirement_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        folder = root / ".agent" / directory
        if not folder.is_dir() or folder.is_symlink():
            return result
        for path in sorted(folder.glob("*.yaml")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                value = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(value, dict):
                continue
            reqs = value.get("requirement_ids", [])
            if value.get("requirement_id") == requirement_id or requirement_id in reqs:
                result.append(value)
        return result

    @staticmethod
    def _memory_markdown(
        requirement: dict[str, Any],
        adrs: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        handoffs: list[dict[str, Any]],
        merged_commit_sha: str,
        pr_number: int | None,
    ) -> str:
        lines = [
            f"# {requirement['id']} — {requirement.get('title', '')}",
            "",
            "> Generated deterministically from merged repository evidence. No chat transcript or model inference is used.",
            "",
            "## Source",
            "",
            f"- Requirement: `{requirement['id']}`",
            f"- Merged commit: `{merged_commit_sha}`",
        ]
        if pr_number is not None:
            lines.append(f"- Pull request: `#{pr_number}`")
        for adr in adrs:
            lines.append(f"- Architecture: `{adr.get('id')}`")

        acceptance = requirement.get("acceptance", [])
        if acceptance:
            lines += ["", "## Acceptance", ""] + [f"- {item}" for item in acceptance]
        rules = requirement.get("business_rules", [])
        if rules:
            lines += ["", "## Business rules", ""] + [f"- {item}" for item in rules]
        if adrs:
            lines += ["", "## Architecture decisions", ""]
            for adr in adrs:
                lines.append(f"### {adr.get('id')} — {adr.get('title', '')}")
                lines.append("")
                decision = yaml.safe_dump(adr.get("decision", {}), allow_unicode=True, sort_keys=False).strip()
                lines += ["```yaml", decision, "```", ""]
        if tasks:
            lines += ["## Completed tasks", ""]
            for task in tasks:
                lines.append(f"- `{task.get('id')}` — {task.get('assigned_agent')} — {task.get('status')}")
        changed = []
        for handoff in handoffs:
            for path in handoff.get("changed_files", []):
                if path not in changed:
                    changed.append(path)
        if changed:
            lines += ["", "## Changed files recorded by handoffs", ""] + [f"- `{path}`" for path in changed]
        return "\n".join(lines).rstrip() + "\n"

    def prepare(
        self,
        requirement_id: str,
        merged_commit_sha: str,
        *,
        pr_number: int | None = None,
        delivery: FeatureDeliveryService | None = None,
        create_pr: bool = False,
        push: bool = False,
        draft_pr: bool = False,
    ) -> MemorySyncResult:
        project = ProjectProtocol(self.repo_root).project()
        default_branch = project["repository"]["default_branch"]
        if not self.git.is_ancestor(merged_commit_sha, default_branch):
            raise MemorySyncError(
                f"Memory source commit {merged_commit_sha} is not merged into {default_branch}"
            )

        worktree, branch = MemoryBranchManager(self.git).create(requirement_id, default_branch)
        protocol = ProjectProtocol(worktree)
        try:
            requirement = protocol.requirement(requirement_id)
        except Exception as exc:
            raise MemorySyncError(
                f"Merged requirement {requirement_id} is not present on {default_branch}"
            ) from exc

        adrs = self._related_yaml(worktree, "decisions", requirement_id)
        tasks = self._related_yaml(worktree, "tasks", requirement_id)
        handoffs = self._related_yaml(worktree, "handoffs", requirement_id)
        # Handoffs normally reference a task instead of requirement directly.
        task_ids = {task.get("id") for task in tasks}
        if task_ids:
            handoff_dir = worktree / ".agent" / "handoffs"
            handoffs = []
            if handoff_dir.is_dir():
                for path in sorted(handoff_dir.glob("*.yaml")):
                    if path.is_symlink() or not path.is_file():
                        continue
                    value = yaml.safe_load(path.read_text(encoding="utf-8"))
                    if isinstance(value, dict) and value.get("task_id") in task_ids:
                        handoffs.append(value)

        token = requirement_id.removeprefix("REQ-")
        memory_id = f"MEM-{token}"
        memory_rel = f".agent/memory/{requirement_id}.md"
        fact_rel = f".agent/facts/{memory_id}.yaml"
        memory_path = worktree / memory_rel
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(
            self._memory_markdown(requirement, adrs, tasks, handoffs, merged_commit_sha, pr_number),
            encoding="utf-8",
        )
        sources = [requirement_id, *[adr.get("id") for adr in adrs if adr.get("id")], f"COMMIT:{merged_commit_sha}"]
        if pr_number is not None:
            sources.append(f"PR:{pr_number}")
        dump_yaml(worktree / fact_rel, {
            "id": memory_id,
            "type": "MEMORY",
            "status": "ACTIVE",
            "statement": f"{requirement_id} has been merged and its durable project memory is recorded in {memory_rel}.",
            "source": sources,
            "superseded_by": None,
        })
        commit_sha = GitRepository(worktree).commit(
            f"docs(memory): record merged {requirement_id}\n\nSource-Commit: {merged_commit_sha}"
        )

        pr = None
        if create_pr:
            if delivery is None:
                raise ValueError("create_pr=True requires FeatureDeliveryService for the memory worktree")
            delivered = delivery.deliver(
                branch,
                f"memory: record merged {requirement_id}",
                f"Durable project memory derived only from merged evidence for {requirement_id}.",
                push=push,
                draft=draft_pr,
            )
            pr = delivered.pull_request

        return MemorySyncResult(
            requirement_id,
            memory_id,
            branch,
            str(worktree),
            commit_sha,
            memory_rel,
            fact_rel,
            pr,
        )
