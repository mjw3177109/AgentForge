"""Readiness preflight is safe, offline and labels absent real evaluations NOT_RUN."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_agentforge_v10_readiness.py"
SPEC = importlib.util.spec_from_file_location("agentforge_v10_readiness", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_no_credentials_does_not_claim_deepseek_acceptance():
    report = MODULE.inspect({})
    assert report["model"]["real_deepseek_three_round_result"] == "NOT_RUN"
    assert report["model"]["credential_configured"] is False
    assert report["production_release_authorized"] is False
    assert report["worker"]["remote_vm_deployed_and_verified"] is False


def test_all_environment_markers_still_do_not_claim_running_real_model():
    report = MODULE.inspect({
        "AGENTFORGE_LLM_API_KEY": "fake-placeholder-secret-not-to-print",
        "AGENTFORGE_V07_PAID_LIVE": "I_APPROVE_THREE_DEEPSEEK_RUNS",
        "AGENTFORGE_WORKER_ROLE": "trusted-dedicated",
    })
    assert report["model"]["real_deepseek_three_round_result"] == "NOT_RUN"
    assert "fake-placeholder-secret-not-to-print" not in str(report)
    assert report["next_action"] == "RUN_EXPLICIT_GATED_REAL_MODEL_WORKFLOW"
