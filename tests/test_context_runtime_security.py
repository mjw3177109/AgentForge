from pathlib import Path
from agentforge.context import ContextBuilder
from test_llm_runtime import make_repo


def test_context_does_not_follow_external_symlink(tmp_path: Path):
    repo = make_repo(tmp_path)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("TOP-SECRET", encoding="utf-8")
    link = repo / "server" / "secret-link"
    try:
        link.symlink_to(outside)
    except OSError:
        return
    ctx = ContextBuilder(repo).build("TASK-000001")
    assert all("TOP-SECRET" not in item["content"] for item in ctx["files"])


def test_context_respects_agent_and_task_read_intersection(tmp_path: Path):
    repo = make_repo(tmp_path)
    (repo / "miniapp/secret.js").write_text("MINIAPP-SECRET", encoding="utf-8")
    ctx = ContextBuilder(repo).build("TASK-000001")
    assert all("MINIAPP-SECRET" not in item["content"] for item in ctx["files"])
