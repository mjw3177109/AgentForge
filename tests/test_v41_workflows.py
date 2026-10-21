from pathlib import Path
import importlib.util
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]

def test_no_automatic_paid_deepseek():
    paid=yaml.load((ROOT/'.github/workflows/agentforge-v41-live.yml').read_text(),Loader=yaml.BaseLoader)
    assert set(paid['on'])=={'workflow_dispatch'}
    assert paid['permissions']=={'contents':'read'}
    assert paid['jobs']['live']['needs']=='offline'
    assert 'AGENTFORGE_LLM_API_KEY' in paid['jobs']['live']['env']
    assert 'AGENTFORGE_V3_EVIDENCE_KEY' not in paid['jobs']['live']['env']
    assert 'AGENTFORGE_V41_ATTEST_KEY' not in paid['jobs']['live']['env']
    attest=paid['jobs']['independent-attestation']
    assert 'AGENTFORGE_V41_ATTEST_KEY' in attest['env']
    assert 'AGENTFORGE_LLM_API_KEY' not in attest['env']
    assert 'trusted_verifier_sha' in paid['on']['workflow_dispatch']['inputs']
    assert paid['jobs']['authorize']['steps'][0]['shell']=='bash'

def test_offline_matrix_python_and_three_iterations():
    offline=yaml.load((ROOT/'.github/workflows/agentforge-v41-offline.yml').read_text(),Loader=yaml.BaseLoader)
    job=offline['jobs']['v41-offline']
    assert job['strategy']['matrix']['python-version']==['3.11','3.12']
    assert 'for iteration in 1 2 3' in job['steps'][-1]['run']
    assert offline['permissions']=={'contents':'read'}

def test_trusted_java_checks_real_service_and_unique_mysql():
    java=(ROOT/'benchmarks/v41_trusted/TrustedPointsExactlyOnceTest.java').read_text()
    for token in ('@EnableTransactionManagement','new PointsService(',
                  'sequentialDuplicateEventCannotDoubleCredit','concurrentDuplicateEventCannotDoubleCredit',
                  'service.earnAfterPayment(','SELECT balance_points FROM points_account',
                  'SELECT COUNT(*) FROM points_ledger','127\\\\.0\\\\.0\\\\.1:3306'):
        assert token in java,token

def test_independent_v41_canary_keeps_original_ten_gates():
    code=(ROOT/'scripts/v41_live_acceptance.py').read_text()
    assert 'v20.verify_snapshot' in code
    assert 'len(gates) != 10' in code
    assert 'check_java_service' in code
    assert 'verify_trace_file' in code
    assert 'P2_EXECUTED_JAVA_EXACTLY_ONCE_GATE' in code


def test_scope_audit_refuses_main(tmp_path, monkeypatch):
    module_path=ROOT/'scripts/v41_scope_audit.py'
    spec=importlib.util.spec_from_file_location('v41_scope_audit_test',module_path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    class R:
        def __init__(self, stdout='',code=0): self.stdout=stdout;self.returncode=code
    monkeypatch.setattr(mod,'_git',lambda repo,*args:
                        R('main\n') if args[:2]==('branch','--show-current') else R())
    result=mod.audit(tmp_path)
    assert result['status']=='BLOCKED' and 'V41_REQUIRES_FEATURE_V4_BRANCH' in result['issues']
