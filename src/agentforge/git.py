from __future__ import annotations
from pathlib import Path
import re
import shutil
import subprocess
from agentforge.errors import GitError


class GitRepository:
    """Deterministic Git control-plane wrapper.

    LLM drivers never receive this object. Only the orchestrator may create
    branches/worktrees, commit verified changes, or push non-default branches.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()

    def _run(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        cmd = ["git", *args]
        proc = subprocess.run(cmd, cwd=cwd or self.root, text=True, capture_output=True)
        if check and proc.returncode != 0:
            raise GitError(f"{' '.join(cmd)} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def ensure(self) -> None:
        try:
            self._run("rev-parse", "--git-dir")
        except GitError as exc:
            raise GitError(f"Not a git repository: {self.root}") from exc

    def current_branch(self, cwd: Path | None = None) -> str:
        branch = self._run("branch", "--show-current", cwd=cwd)
        if not branch:
            raise GitError("Detached HEAD is not allowed for AgentForge task execution")
        return branch

    def head(self, cwd: Path | None = None) -> str:
        return self._run("rev-parse", "HEAD", cwd=cwd)

    def branch_exists(self, branch: str) -> bool:
        proc = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=self.root,
            text=True,
            capture_output=True,
        )
        if proc.returncode not in {0, 1}:
            raise GitError(f"Unable to inspect branch {branch}: {proc.stderr.strip()}")
        return proc.returncode == 0

    def is_ancestor(self, ancestor: str, descendant_ref: str) -> bool:
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant_ref],
            cwd=self.root,
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            return True
        if proc.returncode == 1:
            return False
        raise GitError(
            f"Unable to verify ancestry {ancestor} -> {descendant_ref}: {proc.stderr.strip()}"
        )

    def changed_files(self, cwd: Path | None = None) -> list[str]:
        out = self._run("status", "--porcelain", "-uall", cwd=cwd)
        files: list[str] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            value = line[3:].strip()
            if " -> " in value:
                value = value.split(" -> ", 1)[1]
            files.append(value)
        return files

    def commit(self, message: str, cwd: Path | None = None) -> str:
        wd = cwd or self.root
        self._run("add", "-A", cwd=wd)
        if not self.changed_files(wd):
            return self.head(wd)
        self._run("commit", "-m", message, cwd=wd)
        return self.head(wd)

    def push(self, branch: str, cwd: Path | None = None) -> None:
        if branch in {"main", "master"}:
            raise GitError("AgentForge refuses to push a default branch directly")
        self._run("push", "-u", "origin", branch, cwd=cwd)

    def remote_slug(self, cwd: Path | None = None) -> tuple[str, str]:
        url = self._run("remote", "get-url", "origin", cwd=cwd)
        match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", url)
        if not match:
            raise GitError(f"Cannot infer GitHub owner/repo from origin: {url}")
        return match.group("owner"), match.group("repo")


class WorktreeManager:
    def __init__(self, repo: GitRepository, worktree_root: Path | None = None):
        self.repo = repo
        self.worktree_root = (worktree_root or repo.root.parent / ".agentforge-worktrees").resolve()
        self.worktree_root.mkdir(parents=True, exist_ok=True)

    def create(self, task_id: str, base_branch: str | None = None) -> tuple[Path, str]:
        self.repo.ensure()
        base = base_branch or self.repo.current_branch()
        branch = f"agent/{task_id.lower()}"
        path = self.worktree_root / task_id
        self.repo._run("worktree", "remove", "--force", str(path), check=False)
        if path.exists():
            shutil.rmtree(path)
        self.repo._run("worktree", "prune", check=False)
        self.repo._run("branch", "-D", branch, check=False)
        self.repo._run("worktree", "add", "-b", branch, str(path), base)
        return path, branch

    def remove(self, path: Path) -> None:
        self.repo._run("worktree", "remove", "--force", str(path), check=False)


class FeatureBranchManager:
    """Maintain one integration worktree per feature/requirement."""

    def __init__(self, repo: GitRepository, worktree_root: Path | None = None):
        self.repo = repo
        self.root = (worktree_root or repo.root.parent / ".agentforge-features").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def branch_name(feature_id: str) -> str:
        return f"feature/{feature_id.lower()}"

    def create(self, feature_id: str, base_branch: str | None = None) -> tuple[Path, str]:
        self.repo.ensure()
        base = base_branch or self.repo.current_branch()
        branch = self.branch_name(feature_id)
        path = self.root / feature_id
        self.repo._run("worktree", "remove", "--force", str(path), check=False)
        if path.exists():
            shutil.rmtree(path)
        self.repo._run("worktree", "prune", check=False)
        if not self.repo.branch_exists(branch):
            self.repo._run("branch", branch, base)
        self.repo._run("worktree", "add", str(path), branch)
        return path, branch

    def merge_task(self, feature_worktree: Path, task_branch: str, task_id: str) -> str:
        self.repo._run(
            "merge", "--no-ff", task_branch, "-m", f"merge(agent): integrate {task_id}",
            cwd=feature_worktree,
        )
        return self.repo.head(feature_worktree)
