from pathlib import Path
from agentforge.context import ContextBuilder
from test_llm_runtime import make_repo


def test_context_includes_facts_contracts_memory_and_dependency_handoff(tmp_path: Path):
    repo = make_repo(tmp_path)
    for directory in ["facts", "contracts", "database", "handoffs", "memory"]:
        (repo / ".agent" / directory).mkdir(parents=True, exist_ok=True)
    (repo / ".agent/facts/FACT-AUTH-001.yaml").write_text("id: FACT-AUTH-001\ntype: CONVENTION\nstatement: use CurrentUser\n", encoding="utf-8")
    (repo / ".agent/contracts/API-X-001.yaml").write_text("id: API-X-001\ntype: API\npath: /api/x\n", encoding="utf-8")
    (repo / ".agent/database/DB-X-001.yaml").write_text("id: DB-X-001\ntype: DATABASE\ntable: x\n", encoding="utf-8")
    (repo / ".agent/handoffs/HO-UP.yaml").write_text("handoff_id: HO-UP\ntask_id: TASK-UPSTREAM\nchanged_files: [server/a.java]\n", encoding="utf-8")
    (repo / ".agent/handoffs/HO-OTHER.yaml").write_text("handoff_id: HO-OTHER\ntask_id: TASK-OTHER\nchanged_files: [x]\n", encoding="utf-8")
    (repo / ".agent/memory/business.md").write_text("Merged rule: never guess auth", encoding="utf-8")
    task_path = repo / ".agent/tasks/TASK-000001.yaml"
    text = task_path.read_text(encoding="utf-8").replace("dependencies: []", "dependencies: [TASK-UPSTREAM]")
    task_path.write_text(text, encoding="utf-8")

    ctx = ContextBuilder(repo).build("TASK-000001")
    assert ctx["facts"][0]["id"] == "FACT-AUTH-001"
    assert ctx["contracts"][0]["id"] == "API-X-001"
    assert ctx["database_contracts"][0]["id"] == "DB-X-001"
    assert [h["task_id"] for h in ctx["handoffs"]] == ["TASK-UPSTREAM"]
    assert "never guess auth" in ctx["memory"][0]["content"]
