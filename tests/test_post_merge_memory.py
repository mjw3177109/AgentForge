from __future__ import annotations
from pathlib import Path
import subprocess
import pytest
from agentforge.errors import MemorySyncError
from agentforge.memory import PostMergeMemoryService


def run(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(list(args), cwd=cwd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return proc.stdout.strip()


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "git", "init", "-b", "main")
    run(repo, "git", "config", "user.email", "agentforge@example.local")
    run(repo, "git", "config", "user.name", "AgentForge Test")
    for directory in ["requirements", "decisions", "tasks", "handoffs", "facts", "memory"]:
        (repo / ".agent" / directory).mkdir(parents=True, exist_ok=True)
    (repo / ".agent/project.yaml").write_text("project:\n  id: SHOP001\n  name: demo\n  version: '1'\nrepository:\n  provider: github\n  default_branch: main\nstack: {}\nrules:\n  direct_main_write: false\n  require_pr: true\n  require_ci: true\n  require_fact_reference: true\n", encoding="utf-8")
    (repo / ".agent/constitution.md").write_text("Merged memory only.\n", encoding="utf-8")
    (repo / "README.md").write_text("base\n")
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-m", "init")
    return repo


def create_feature(repo: Path) -> str:
    run(repo, "git", "checkout", "-b", "feature/req-000777")
    (repo / ".agent/requirements/REQ-000777.yaml").write_text("id: REQ-000777\ntitle: 收藏\nstatus: DONE\nbusiness_rules: [不能重复收藏]\nacceptance: [收藏功能可用]\n", encoding="utf-8")
    (repo / ".agent/decisions/ADR-000777.yaml").write_text("id: ADR-000777\ntitle: 收藏架构\nstatus: ACCEPTED\nrequirement_ids: [REQ-000777]\ndecision:\n  backend: {change_required: true}\n", encoding="utf-8")
    (repo / ".agent/tasks/TASK-000777.yaml").write_text("id: TASK-000777\nrequirement_ids: [REQ-000777]\nadr_ids: [ADR-000777]\nassigned_agent: backend\ndependencies: []\nscope: {read: ['**'], write: ['server/**'], deny: []}\nacceptance: [works]\nverification: []\nstatus: DONE\n", encoding="utf-8")
    (repo / ".agent/handoffs/HO-000777.yaml").write_text("handoff_id: HO-000777\ntask_id: TASK-000777\nsource_agent: backend\nchanged_files: [server/Favorite.java]\nevidence: [REQ-000777, ADR-000777]\n", encoding="utf-8")
    (repo / "server").mkdir()
    (repo / "server/Favorite.java").write_text("class Favorite {}\n")
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-m", "feat: favorite")
    return run(repo, "git", "rev-parse", "HEAD")


def test_unmerged_feature_cannot_write_memory(tmp_path: Path):
    repo = init_repo(tmp_path)
    feature_sha = create_feature(repo)
    run(repo, "git", "checkout", "main")
    with pytest.raises(MemorySyncError, match="not merged"):
        PostMergeMemoryService(repo).prepare("REQ-000777", feature_sha)
    assert run(repo, "git", "branch", "--list", "memory/req-000777") == ""


def test_merged_feature_creates_reviewable_memory_branch_not_main(tmp_path: Path):
    repo = init_repo(tmp_path)
    feature_sha = create_feature(repo)
    run(repo, "git", "checkout", "main")
    run(repo, "git", "merge", "--no-ff", "feature/req-000777", "-m", "merge favorite")
    main_before = run(repo, "git", "rev-parse", "HEAD")

    result = PostMergeMemoryService(repo).prepare("REQ-000777", feature_sha, pr_number=42)
    memory = Path(result.worktree)
    text = (memory / result.memory_path).read_text(encoding="utf-8")
    fact = (memory / result.fact_path).read_text(encoding="utf-8")

    assert result.branch == "memory/req-000777"
    assert "REQ-000777" in text
    assert feature_sha in text
    assert "#42" in text
    assert "不能重复收藏" in text
    assert "server/Favorite.java" in text
    assert "COMMIT:" + feature_sha in fact
    assert run(repo, "git", "rev-parse", "HEAD") == main_before
    assert not (repo / result.memory_path).exists()
    assert run(memory, "git", "status", "--porcelain") == ""


def test_memory_requires_requirement_to_exist_on_default_branch(tmp_path: Path):
    repo = init_repo(tmp_path)
    sha = run(repo, "git", "rev-parse", "HEAD")
    with pytest.raises(MemorySyncError, match="not present"):
        PostMergeMemoryService(repo).prepare("REQ-DOES-NOT-EXIST", sha)
