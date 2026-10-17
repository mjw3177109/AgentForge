from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from agentforge.errors import GitError
from agentforge.git import GitRepository
from agentforge.github import GitHubAppClient
from agentforge.protocol.loader import ProjectProtocol


@dataclass
class DeliveryResult:
    owner: str
    repo: str
    branch: str
    base: str
    head_sha: str
    pull_request: dict


class FeatureDeliveryService:
    """Push an already verified feature branch and open a PR.

    This object is control-plane only. It is never passed to LLM drivers and it
    intentionally has no merge method.
    """

    def __init__(self, feature_worktree: Path, github: GitHubAppClient):
        self.worktree = feature_worktree.resolve()
        self.git = GitRepository(self.worktree)
        self.github = github

    def deliver(
        self,
        feature_branch: str,
        title: str,
        body: str,
        *,
        push: bool = True,
        draft: bool = False,
    ) -> DeliveryResult:
        self.git.ensure()
        if feature_branch in {"main", "master"}:
            raise GitError("Default branch delivery is forbidden")
        current = self.git.current_branch()
        if current != feature_branch:
            raise GitError(f"Feature worktree branch mismatch: expected {feature_branch}, got {current}")
        owner, repo = self.git.remote_slug()
        self.github.get_repository(owner, repo)
        if push:
            self.git.push(feature_branch)
        base = ProjectProtocol(self.worktree).project()["repository"]["default_branch"]
        pr = self.github.create_pull_request(owner, repo, feature_branch, base, title, body, draft=draft)
        return DeliveryResult(owner, repo, feature_branch, base, self.git.head(), pr)

    def read_ci(self, sha: str | None = None) -> dict:
        owner, repo = self.git.remote_slug()
        return self.github.ci_snapshot(owner, repo, sha or self.git.head())
