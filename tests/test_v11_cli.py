"""V1.1 protocol: paid runner has no fake path and requires explicit opt-in."""
from pathlib import Path


def test_paid_workflow_is_gated_and_offline_is_separate():
    root = Path(__file__).resolve().parents[1]
    live = (root / "scripts/run_django_v11_live.py").read_text("utf-8")
    offline = (root / "scripts/run_django_v11_offline.py").read_text("utf-8")
    workflow = (root / ".github/workflows/agentforge-django-v11-live.yml").read_text("utf-8")
    assert "FakeScenarioAgent" not in live
    assert "--confirm-paid-calls" in live
    assert "create_v05_broker(max_requests=5)" in live
    assert "SCRIPTED_FAKE_AGENT" in offline
    assert "artifacts/django-v11/offline-report.json" in offline
    assert "REAL_DEEPSEEK" in live
    assert "vars.AGENTFORGE_V07_PAID_LIVE" in workflow
    assert "secrets.AGENTFORGE_LLM_API_KEY" in workflow
    assert "workflow_dispatch" in workflow
    # V1.3 intentionally removed push; paid calls must require manual dispatch.
    assert "  workflow_dispatch:" in workflow
    assert "  push:" not in workflow
    assert "--checkpoint" in workflow
    assert "run_django_v11_live.py --confirm-paid-calls" in workflow
