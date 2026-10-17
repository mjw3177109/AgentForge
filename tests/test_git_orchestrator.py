from __future__ import annotations
from pathlib import Path
import subprocess
from agentforge.git import FeatureBranchManager, GitRepository, WorktreeManager
from agentforge.llm.base import AgentDriver
from agentforge.models import AgentAction
from agentforge.orchestrator import FeatureOrchestrator, TaskOrchestrator


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(list(args), cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "git", "init", "-b", "main")
    run(repo, "git", "config", "user.email", "agentforge@example.local")
    run(repo, "git", "config", "user.name", "AgentForge Test")
    (repo / ".agent/tasks").mkdir(parents=True)
    (repo / ".agent/requirements").mkdir(parents=True)
    (repo / ".agent/policies").mkdir(parents=True)
    (repo / "server").mkdir()
    (repo / ".agent/constitution.md").write_text("Do not guess.\n", encoding="utf-8")
    (repo / ".agent/project.yaml").write_text("project:\n  id: P1\n  name: demo\n  version: '1'\nrepository:\n  provider: github\n  default_branch: main\nstack: {}\nrules:\n  direct_main_write: false\n  require_pr: true\n  require_ci: true\n  require_fact_reference: true\n", encoding="utf-8")
    (repo / ".agent/requirements/REQ-000001.yaml").write_text("id: REQ-000001\ntitle: Demo\nstatus: READY\nacceptance: [works]\n", encoding="utf-8")
    (repo / ".agent/tasks/TASK-000001.yaml").write_text("id: TASK-000001\nrequirement_ids: [REQ-000001]\nassigned_agent: backend\ndependencies: []\nscope:\n  read: ['.agent/**', 'server/**']\n  write: ['server/**']\n  deny: ['miniapp/**']\nacceptance: [works]\nverification: [generated]\nstatus: READY\n", encoding="utf-8")
    (repo / ".agent/policies/verification.yaml").write_text("checks:\n  generated:\n    type: file_exists\n    path: server/generated.txt\n", encoding="utf-8")
    (repo / "server/existing.txt").write_text("base", encoding="utf-8")
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-m", "init")
    return repo


class WriteDriver(AgentDriver):
    def execute(self, prompt: str, context: dict) -> AgentAction:
        return AgentAction.model_validate({
            "status": "SUCCESS",
            "summary": "generated",
            "evidence": ["TASK-000001", "REQ-000001"],
            "operations": [{"type": "write_file", "path": "server/generated.txt", "content": "ok"}],
            "block": None,
        })


def test_task_orchestrator_uses_worktree_verifies_and_commits(tmp_path: Path):
    repo = init_repo(tmp_path)
    result = TaskOrchestrator(repo, WriteDriver()).run_task("TASK-000001", base_branch="main")
    assert result.status == "DONE"
    assert result.branch == "agent/task-000001"
    assert result.commit_sha
    assert result.transitions == ["READY->RUNNING", "RUNNING->VERIFYING", "VERIFYING->DONE"]
    assert result.verification[0]["returncode"] == 0
    assert (Path(result.worktree) / "server/generated.txt").read_text() == "ok"
    assert not (repo / "server/generated.txt").exists()


def test_feature_orchestrator_integrates_only_verified_task_commit(tmp_path: Path):
    repo = init_repo(tmp_path)
    result = FeatureOrchestrator(repo, WriteDriver()).run_task("REQ-000001", "TASK-000001", base_branch="main")
    assert result.task.status == "DONE"
    assert result.integration_sha
    feature = Path(result.feature_worktree)
    assert (feature / "server/generated.txt").read_text() == "ok"
    log = run(feature, "git", "log", "--oneline", "-3")
    assert "integrate TASK-000001" in log


def test_same_task_worktree_can_be_recreated(tmp_path: Path):
    repo = init_repo(tmp_path)
    manager = WorktreeManager(GitRepository(repo), tmp_path / "task-worktrees")
    first, branch1 = manager.create("TASK-REPEAT", "main")
    assert first.exists()
    second, branch2 = manager.create("TASK-REPEAT", "main")
    assert second.exists()
    assert branch1 == branch2 == "agent/task-repeat"
