from __future__ import annotations
from pathlib import Path
import subprocess
import yaml
import pytest
from agentforge.errors import PlanningError
from agentforge.llm.base import AgentDriver
from agentforge.models import AgentAction
from agentforge.planning import FeaturePlanningPipeline


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(list(args), cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "git", "init", "-b", "main")
    run(repo, "git", "config", "user.email", "agentforge@example.local")
    run(repo, "git", "config", "user.name", "AgentForge Test")
    for directory in ["requirements", "decisions", "tasks", "policies"]:
        (repo / ".agent" / directory).mkdir(parents=True, exist_ok=True)
    (repo / ".agent/project.yaml").write_text("project:\n  id: SHOP001\n  name: demo\n  version: '1'\nrepository:\n  provider: github\n  default_branch: main\nstack: {}\nrules:\n  direct_main_write: false\n  require_pr: true\n  require_ci: true\n  require_fact_reference: true\n", encoding="utf-8")
    (repo / ".agent/constitution.md").write_text("Do not guess.\n", encoding="utf-8")
    (repo / ".agent/policies/verification.yaml").write_text("checks:\n  backend-test: {type: directory_exists, path: .agent}\n  miniapp-check: {type: directory_exists, path: .agent}\n", encoding="utf-8")
    (repo / "README.md").write_text("base", encoding="utf-8")
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-m", "init")
    return repo


class PlanningDriver(AgentDriver):
    def __init__(self, include_admin: bool = False, cyclic: bool = False):
        self.calls = 0
        self.include_admin = include_admin
        self.cyclic = cyclic

    def execute(self, prompt: str, context: dict) -> AgentAction:
        self.calls += 1
        if self.calls == 1:
            req_id = context["required_id"]
            payload = {
                "id": req_id,
                "title": "商品收藏",
                "status": "READY",
                "acceptance": ["用户可以收藏商品"],
                "out_of_scope": ["管理后台收藏管理"],
                "out_of_scope_modules": ["admin"],
            }
            return AgentAction.model_validate({"status":"SUCCESS","summary":"req","evidence":[],"operations":[{"type":"write_file","path":context["target_path"],"content":yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)}],"block":None})
        if self.calls == 2:
            req_id = context["requirement"]["id"]
            adr_id = context["required_id"]
            payload = {
                "id": adr_id,
                "title": "收藏架构",
                "status": "ACCEPTED",
                "requirement_ids": [req_id],
                "decision": {"admin": {"change_required": False}, "backend": {"change_required": True}},
            }
            return AgentAction.model_validate({"status":"SUCCESS","summary":"adr","evidence":[req_id],"operations":[{"type":"write_file","path":context["target_path"],"content":yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)}],"block":None})

        req_id = context["requirement"]["id"]
        adr_id = context["architecture"]["id"]
        ids = context["allowed_task_ids"]
        backend_id, review_id = ids[0], ids[1]
        backend_deps = [review_id] if self.cyclic else []
        tasks = [
            {
                "id": backend_id, "requirement_ids":[req_id], "adr_ids":[adr_id], "assigned_agent":"backend",
                "dependencies":backend_deps,
                "scope":{"read":[".agent/**","server/**"],"write":["server/**"],"deny":["miniapp/**","admin-web/**"]},
                "acceptance":["backend works"], "verification":["backend-test"], "status":"PENDING",
            },
            {
                "id": review_id, "requirement_ids":[req_id], "adr_ids":[adr_id], "assigned_agent":"reviewer",
                "dependencies":[backend_id], "scope":{"read":["**"],"write":[],"deny":[]},
                "acceptance":["review"], "verification":[], "status":"PENDING",
            },
        ]
        if self.include_admin:
            admin_id = ids[2]
            tasks.append({
                "id":admin_id,"requirement_ids":[req_id],"adr_ids":[adr_id],"assigned_agent":"admin",
                "dependencies":[],"scope":{"read":[".agent/**","admin-web/**"],"write":["admin-web/**"],"deny":[]},
                "acceptance":["admin"],"verification":["backend-test"],"status":"PENDING",
            })
        operations = []
        for task in tasks:
            operations.append({"type":"write_file","path":f".agent/tasks/{task['id']}.yaml","content":yaml.safe_dump(task, allow_unicode=True, sort_keys=False)})
        return AgentAction.model_validate({"status":"SUCCESS","summary":"plan","evidence":[req_id,adr_id],"operations":operations,"block":None})


def test_planning_pipeline_generates_req_adr_and_acyclic_tasks_on_feature_branch(tmp_path: Path):
    repo = make_repo(tmp_path)
    result = FeaturePlanningPipeline(repo, PlanningDriver()).plan("增加商品收藏", base_branch="main")
    assert result.requirement_id.startswith("REQ-")
    assert result.adr_id.startswith("ADR-")
    assert len(result.task_ids) == 2
    feature = Path(result.feature_worktree)
    assert (feature / ".agent/requirements" / f"{result.requirement_id}.yaml").is_file()
    assert not (repo / ".agent/requirements" / f"{result.requirement_id}.yaml").exists()
    assert run(feature, "git", "status", "--porcelain") == ""


def test_planner_cannot_reintroduce_explicitly_out_of_scope_admin(tmp_path: Path):
    repo = make_repo(tmp_path)
    with pytest.raises(PlanningError, match="out-of-scope"):
        FeaturePlanningPipeline(repo, PlanningDriver(include_admin=True)).plan("增加商品收藏", base_branch="main")


def test_planner_cycle_is_rejected_before_development(tmp_path: Path):
    repo = make_repo(tmp_path)
    with pytest.raises(PlanningError, match="cycle"):
        FeaturePlanningPipeline(repo, PlanningDriver(cyclic=True)).plan("增加商品收藏", base_branch="main")
