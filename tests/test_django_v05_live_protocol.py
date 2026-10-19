"""No live LLM here: file fixtures only, never mark simulated as 3/3 real."""
import ast
from pathlib import Path

def test_live_command_is_explicit_opt_in_and_no_fake_fallback():
    script = Path(__file__).resolve().parents[1] / "scripts/run_django_v05_live_acceptance.py"
    content = script.read_text("utf-8")
    ast.parse(content)
    assert "--confirm-paid-calls" in content
    assert "run_live_three()" in content
    assert "ScriptedFakeAgent" not in content
    assert '"production_release_authorized": False' in content
