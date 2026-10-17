from __future__ import annotations
from pathlib import Path
import subprocess
import yaml
from agentforge.llm.base import AgentDriver
from agentforge.models import AgentAction
from agentforge.live_feature import LiveFeaturePipeline


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(list(args), cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "git", "init", "-b", "main")
    run(repo, "git", "config", "user.email", "agentforge@example.local")
    run(repo, "git", "config", "user.name", "AgentForge Test")
    for directory in ["requirements", "decisions", "tasks", "policies", "facts", "contracts", "database", "handoffs", "memory", "state"]:
        (repo / ".agent" / directory).mkdir(parents=True, exist_ok=True)
    (repo / ".agent/project.yaml").write_text("project:\n  id: SHOP001\n  name: demo\n  version: '1'\nrepository:\n  provider: github\n  default_branch: main\nstack: {}\nrules:\n  direct_main_write: false\n  require_pr: true\n  require_ci: true\n  require_fact_reference: true\n", encoding="utf-8")
    (repo / ".agent/constitution.md").write_text("Do not guess.\n", encoding="utf-8")
    (repo / ".agent/facts/FACT-AUTH-001.yaml").write_text("id: FACT-AUTH-001\ntype: CONVENTION\nstatement: use CurrentUser\n", encoding="utf-8")
    (repo / ".agent/memory/business.md").write_text("Merged memory survives chats.\n", encoding="utf-8")
    (repo / ".agent/policies/verification.yaml").write_text("checks:\n  generated:\n    type: file_exists\n    path: server/feature.txt\n", encoding="utf-8")
    (repo / "server").mkdir()
    (repo / "server/base.txt").write_text("base")
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-m", "init")
    return repo


class EndToEndDriver(AgentDriver):
    def execute(self, prompt: str, context: dict) -> AgentAction:
        if "user_requirement" in context:
            req_id = context["required_id"]
            req = {"id":req_id,"title":"收藏","status":"READY","acceptance":["works"],"out_of_scope_modules":["admin"]}
            return AgentAction.model_validate({"status":"SUCCESS","summary":"req","evidence":[],"operations":[{"type":"write_file","path":context["target_path"],"content":yaml.safe_dump(req, allow_unicode=True, sort_keys=False)}],"block":None})
        if "required_id" in context and "requirement" in context:
            req_id = context["requirement"]["id"]
            adr_id = context["required_id"]
            adr = {"id":adr_id,"title":"收藏架构","status":"ACCEPTED","requirement_ids":[req_id],"decision":{"admin":{"change_required":False},"backend":{"change_required":True}}}
            return AgentAction.model_validate({"status":"SUCCESS","summary":"adr","evidence":[req_id],"operations":[{"type":"write_file","path":context["target_path"],"content":yaml.safe_dump(adr, allow_unicode=True, sort_keys=False)}],"block":None})
        if "allowed_task_ids" in context:
            req_id = context["requirement"]["id"]
            adr_id = context["architecture"]["id"]
            backend_id, reviewer_id = context["allowed_task_ids"][:2]
            backend = {"id":backend_id,"requirement_ids":[req_id],"adr_ids":[adr_id],"assigned_agent":"backend","dependencies":[],"scope":{"read":[".agent/**","server/**"],"write":["server/**"],"deny":["admin-web/**","miniapp/**"]},"acceptance":["feature file exists"],"verification":["generated"],"status":"PENDING"}
            reviewer = {"id":reviewer_id,"requirement_ids":[req_id],"adr_ids":[adr_id],"assigned_agent":"reviewer","dependencies":[backend_id],"scope":{"read":["**"],"write":[],"deny":[]},"acceptance":["review"],"verification":[],"status":"PENDING"}
            ops=[]
            for task in [backend, reviewer]:
                ops.append({"type":"write_file","path":f".agent/tasks/{task['id']}.yaml","content":yaml.safe_dump(task, allow_unicode=True, sort_keys=False)})
            return AgentAction.model_validate({"status":"SUCCESS","summary":"plan","evidence":[req_id,adr_id],"operations":ops,"block":None})

        task = context["task"]
        evidence = [task["id"], *task.get("requirement_ids", []), *task.get("adr_ids", [])]
        if task["assigned_agent"] == "backend":
            assert any(f.get("id") == "FACT-AUTH-001" for f in context["facts"])
            assert any("Merged memory" in m["content"] for m in context["memory"])
            return AgentAction.model_validate({"status":"SUCCESS","summary":"backend","evidence":evidence,"operations":[{"type":"write_file","path":"server/feature.txt","content":"implemented"}],"block":None})
        if task["assigned_agent"] == "reviewer":
            assert context["handoffs"], "reviewer must see upstream handoff"
            assert any(item["path"] == "server/feature.txt" for item in context["files"])
            return AgentAction.model_validate({"status":"SUCCESS","summary":"review pass","evidence":evidence,"operations":[],"block":None})
        raise AssertionError(task["assigned_agent"])


def test_live_feature_pipeline_closes_plan_develop_handoff_review_and_final_verify(tmp_path: Path):
    repo = make_repo(tmp_path)
    result = LiveFeaturePipeline(repo, EndToEndDriver()).run("增加商品收藏", base_branch="main")
    assert result.status == "PR_READY"
    assert len(result.task_results) == 2
    assert len(result.handoff_ids) == 2
    assert result.final_verification[0]["returncode"] == 0
    feature = Path(result.feature_worktree)
    assert (feature / "server/feature.txt").read_text() == "implemented"
    assert not (repo / "server/feature.txt").exists()
    assert (feature / ".agent/handoffs" / f"{result.handoff_ids[0]}.yaml").is_file()
    state = (feature / ".agent/state/project-state.json").read_text()
    assert "PR_READY" in state
    assert run(feature, "git", "status", "--porcelain") == ""
