"""Static protocol gate: opt-in paid run is never scheduled by ordinary pushes."""
from pathlib import Path


def test_live_workflow_is_disabled_without_explicit_repository_variable():
    root = Path(__file__).resolve().parents[1]
    body = (root / ".github/workflows/agentforge-django-v07-live-gated.yml").read_text("utf-8")
    assert "AGENTFORGE_V07_PAID_LIVE" in body
    assert "I_APPROVE_THREE_DEEPSEEK_RUNS" in body
    assert "workflow_dispatch" in body
    assert "paths:" in body
    assert "- .github/workflows/agentforge-django-v07-live-gated.yml" in body
    assert "secrets.AGENTFORGE_LLM_API_KEY" in body
    assert "--confirm-paid-calls" in body
    assert "SYNTHETIC" not in body.split("jobs:", 1)[-1] or "synthetic Django" in body
