from __future__ import annotations
from pathlib import Path
import json
import subprocess
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from agentforge.delivery import FeatureDeliveryService
from agentforge.errors import GitError
from agentforge.github import GitHubAppClient


def private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_github_app_token_pr_and_ci_read_flow():
    calls = {"token": 0, "pr": 0}

    def handler(request: httpx.Request):
        path = request.url.path
        if path == "/app/installations/99/access_tokens":
            calls["token"] += 1
            assert request.headers["Authorization"].startswith("Bearer ")
            return httpx.Response(201, json={"token": "installation-token"})
        assert request.headers["Authorization"] == "Bearer installation-token"
        if path == "/repos/acme/shop":
            return httpx.Response(200, json={"full_name": "acme/shop"})
        if path == "/repos/acme/shop/pulls":
            calls["pr"] += 1
            body = json.loads(request.content)
            assert body["head"] == "feature/req-1"
            assert body["base"] == "main"
            return httpx.Response(201, json={"number": 7, "html_url": "https://example/pr/7", "state": "open"})
        if path == "/repos/acme/shop/commits/abc/status":
            return httpx.Response(200, json={"state": "success", "statuses": [{"context": "legacy", "state": "success"}]})
        if path == "/repos/acme/shop/commits/abc/check-runs":
            return httpx.Response(200, json={"check_runs": [{"name": "tests", "status": "completed", "conclusion": "success"}]})
        return httpx.Response(404, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gh = GitHubAppClient("123", "99", private_key_pem(), "https://api.github.test", client=client)
    assert gh.get_repository("acme", "shop")["full_name"] == "acme/shop"
    pr = gh.create_pull_request("acme", "shop", "feature/req-1", "main", "title", "body")
    assert pr["number"] == 7
    assert gh.ci_snapshot("acme", "shop", "abc")["state"] == "SUCCESS"
    assert calls == {"token": 1, "pr": 1}


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(list(args), cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


class FakeGitHub:
    def __init__(self): self.created = []
    def get_repository(self, owner, repo): return {"full_name": f"{owner}/{repo}"}
    def create_pull_request(self, owner, repo, head, base, title, body, draft=False):
        self.created.append((owner, repo, head, base, title, draft))
        return {"number": 9, "html_url": "https://example/pr/9", "state": "open"}
    def ci_snapshot(self, owner, repo, sha): return {"state": "SUCCESS"}


def make_feature_repo(tmp_path: Path, branch: str = "feature/req-1") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "git", "init", "-b", "main")
    run(repo, "git", "config", "user.email", "agentforge@example.local")
    run(repo, "git", "config", "user.name", "AgentForge Test")
    (repo / ".agent").mkdir()
    (repo / ".agent/project.yaml").write_text("project:\n  id: P1\n  name: demo\n  version: '1'\nrepository:\n  provider: github\n  default_branch: main\nstack: {}\nrules:\n  direct_main_write: false\n  require_pr: true\n  require_ci: true\n  require_fact_reference: true\n", encoding="utf-8")
    (repo / "README.md").write_text("x")
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-m", "init")
    run(repo, "git", "remote", "add", "origin", "git@github.com:acme/shop.git")
    run(repo, "git", "checkout", "-b", branch)
    return repo


def test_delivery_opens_pr_without_exposing_merge(tmp_path: Path):
    repo = make_feature_repo(tmp_path)
    fake = FakeGitHub()
    service = FeatureDeliveryService(repo, fake)
    result = service.deliver("feature/req-1", "Feature", "Body", push=False)
    assert result.base == "main"
    assert result.pull_request["number"] == 9
    assert fake.created[0][2] == "feature/req-1"
    assert not hasattr(service, "merge")


def test_delivery_refuses_default_branch(tmp_path: Path):
    repo = make_feature_repo(tmp_path, branch="feature/req-1")
    with pytest.raises(GitError):
        FeatureDeliveryService(repo, FakeGitHub()).deliver("main", "x", "y", push=False)
