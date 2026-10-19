"""Markdown exporter keeps model provenance separate and omits unknown fields."""
import importlib.util
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "scripts/render_django_v12_report.py"
SPEC = importlib.util.spec_from_file_location("agentforge_v12_report", FILE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_fake_never_becomes_real_or_renders_secrets():
    text = MODULE.render({
        "model_kind": "SCRIPTED_FAKE_AGENT",
        "overall": "PASS", "cases_passed": 3,
        "cases": [{"case_id": "arith-001", "status": "PASS",
                   "internal_secret": "DO_NOT_PRINT",
                   "failure_class": "DO_NOT_PRINT"}],
        "v12_metrics": {"provider_usage_coverage": "NOT_APPLICABLE"},
    })
    assert "not real DeepSeek" in text
    assert "DO_NOT_PRINT" not in text
    assert text.count("arith-001") == 1
    assert text.count("pricing-002") == 1
    assert text.count("access-003") == 1


def test_invalid_untrusted_attributes_do_not_enter_markdown():
    output = MODULE.render({
        "model_kind": "REAL_DEEPSEEK<script>",
        "overall": "<img>", "cases_passed": "three",
        "cases": [{"case_id": "access-003", "status": "<script>",
                   "repair_path": "<unsafe>", "final_test_count": 5,
                   "model_evidence": {"attempted_requests": 4,
                                      "usage_coverage": "COMPLETE"}}],
    })
    assert "<script>" not in output and "<unsafe>" not in output
    assert "Unverified provenance" in output
    assert "UNKNOWN" in output
