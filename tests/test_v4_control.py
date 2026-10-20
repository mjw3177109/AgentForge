"""Offline-only zero-trust V4 negative, compatibility and operator tests."""
from __future__ import annotations
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import copy
import hashlib
import json
import os

import pytest

from agentforge.v4 import (ControlDenied, Usage, check_budget, detect_stacks,
                           evaluate_request, issue_approval, verify_approval,
                           read_journal, append_journal, verify_p41_evidence)
from agentforge.v4.core import strict_path, read_profiles, canonical
from agentforge.v4.cli import main

SECRET = 'not-a-real-secret-operator-key-123456789'
AUDIT = 'audit-key-long-enough-for-tests-0123456789'
COMMIT = 'f' * 40


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    (root / '.agent').mkdir(parents=True)
    (root / '.agent/execution-profiles.yaml').write_text('''\nallowed_verification_executables: [node, mvn]\nagents:\n  backend:\n    read_scope: [server/**, .agent/**]\n    write_scope: [server/src/main/**]\n    deny_scope: [server/src/main/secrets/**]\n  database:\n    read_scope: [database/**, .agent/**]\n    write_scope: [database/migrations/**]\n    deny_scope: [server/**]\n''')
    (root / 'server/src/main/java').mkdir(parents=True)
    (root / 'server/src/main/java/Foo.java').write_text('class Foo {}')
    (root / 'server/pom.xml').write_text('<project/>')
    (root / 'pyproject.toml').write_text('[build-system]')
    return root


@pytest.fixture
def proposal():
    return {
        'schema': 'agentforge.control.v4/1',
        'project': 'mjw3177109/AgentForge',
        'commit': COMMIT,
        'run_id': 'RUN-v4-test-001',
        'task_id': 'TASK-000001',
        'agent': 'backend',
        'action': 'PROPOSE_EDIT',
        'paths': ['server/src/main/java/Foo.java'],
        'budget': {'max_attempts': 2, 'max_cost_usd': 5, 'max_runtime_seconds': 100},
    }


def preflight(root, data):
    return evaluate_request(root, '.agent/execution-profiles.yaml', data)


def test_safe_proposal_does_not_execute_or_approve(repo, proposal):
    a = preflight(repo, proposal)
    assert a.decision == 'SCOPE_PRECHECK_OK' and not a.executed and not a.verified
    assert not a.permission_expanded
    assert 'spring-module' in a.observed_adapters


def test_adapter_detection_for_django_is_read_only(repo):
    (repo / 'manage.py').write_text('print("DO_NOT_RUN")')
    items = detect_stacks(repo)
    django = next(x for x in items if x.stack == 'django')
    assert django.suggested_checks == (('python', 'manage.py', 'check'),)
    assert django.executable is False


def test_high_risk_proposal_requires_human(repo, proposal):
    (repo / 'server/src/main/security').mkdir()
    proposal['paths'] = ['server/src/main/security/access.java']
    a = preflight(repo, proposal)
    assert a.decision == 'AWAITING_HUMAN_APPROVAL' and a.risk == 'CRITICAL'


def test_database_migration_high_risk(repo, proposal):
    proposal.update(agent='database', paths=['database/migrations/V1__safe.sql'])
    a = preflight(repo, proposal)
    assert a.decision == 'AWAITING_HUMAN_APPROVAL' and a.risk == 'HIGH'


def test_reviewer_test_directory_refused(repo, proposal):
    proposal['paths'] = ['server/src/test/java/UnapprovedTest.java']
    a = preflight(repo, proposal)
    assert a.decision == 'BLOCKED' and 'SCOPE_OR_PATH_DENIED' in a.reason_codes


@pytest.mark.parametrize('path', [
    '../server/src/main/java/a', '/etc/passwd', 'C:/foo', 'server//src/main/a',
    'server/./src/main/a', 'server/src/main/../test/A',
    '.git/config', '.github/workflows/ci.yml', 'server/src/main/*.java',
    'server\\src\\main\\hack', 'server/src/main/', 'server/src/main/a\x00',
])
def test_unsafe_paths_denied(path):
    with pytest.raises(ControlDenied):
        strict_path(path)


def test_symlink_target_or_parent_denied(repo, proposal, tmp_path):
    (repo / 'server/src/main/java/evil.java').symlink_to(tmp_path / 'outside')
    proposal['paths'] = ['server/src/main/java/evil.java']
    a = preflight(repo, proposal)
    assert a.decision == 'BLOCKED'


def test_hardlink_target_denied(repo, proposal):
    source = repo / 'server/src/main/java/Foo.java'
    os.link(source, repo / 'server/src/main/java/Clone.java')
    assert preflight(repo, proposal).decision == 'BLOCKED'


def test_unknown_agent_denied(repo, proposal):
    proposal['agent'] = 'admin'
    with pytest.raises(ControlDenied, match='Unknown agent'):
        preflight(repo, proposal)


def test_task_cannot_add_write_scope(repo, proposal):
    proposal['write_scope'] = ['**']
    with pytest.raises(ControlDenied):
        preflight(repo, proposal)


def test_only_allowed_actions(repo, proposal):
    proposal['action'] = 'DEPLOY_PRODUCTION'
    with pytest.raises(ControlDenied):
        preflight(repo, proposal)


@pytest.mark.parametrize('field,value', [('max_attempts', 4), ('max_attempts', True),
                                         ('max_runtime_seconds', 0), ('max_runtime_seconds', 3601),
                                         ('max_cost_usd', -1), ('max_cost_usd', 101),
                                         ('max_cost_usd', float('inf'))])
def test_budget_limits_fail_closed(repo, proposal, field, value):
    proposal['budget'][field] = value
    with pytest.raises((ControlDenied, ValueError)):
        preflight(repo, proposal)


def high_risk(repo, proposal):
    proposal['paths'] = ['server/src/main/security/auth.java']
    return preflight(repo, proposal)


def test_approval_binds_request_commit_and_profile(repo, proposal):
    a = high_risk(repo, proposal)
    token = issue_approval(a, proposal, operator='owner-001', secret=SECRET, now=1000)
    approved = verify_approval(token, a, proposal, secret=SECRET, now=1100)
    assert approved['authorized'] is True and approved['scope_extended'] is False
    other = copy.deepcopy(proposal)
    other['commit'] = 'a' * 40
    with pytest.raises(ControlDenied):
        verify_approval(token, a, other, secret=SECRET, now=1100)
    changed = copy.deepcopy(proposal)
    changed['run_id'] = 'RUN-another-0001'
    with pytest.raises(ControlDenied):
        verify_approval(token, a, changed, secret=SECRET, now=1100)
    (repo / '.agent/execution-profiles.yaml').write_text('agents: {}')
    with pytest.raises(ControlDenied):
        preflight(repo, proposal)


def test_token_tamper_expiry_short_secret(repo, proposal):
    a = high_risk(repo, proposal)
    token = issue_approval(a, proposal, operator='owner-001', secret=SECRET, now=1000, ttl_seconds=60)
    with pytest.raises(ControlDenied):
        verify_approval(token, a, proposal, secret=SECRET, now=1060)
    with pytest.raises(ControlDenied):
        verify_approval(token[:-4] + 'aaaa', a, proposal, secret=SECRET, now=1010)
    with pytest.raises(ControlDenied):
        issue_approval(a, proposal, operator='owner-001', secret='short')
    with pytest.raises(ControlDenied):
        issue_approval(a, proposal, operator='owner-001', secret=SECRET, ttl_seconds=3601)


def test_safe_low_risk_not_signable(repo, proposal):
    a = preflight(repo, proposal)
    with pytest.raises(ControlDenied):
        issue_approval(a, proposal, operator='owner-001', secret=SECRET)


def test_kill_switch_blocks_all(repo, proposal):
    (repo / '.agent/v4').mkdir()
    (repo / '.agent/v4/KILL_SWITCH').write_text('STOP')
    with pytest.raises(ControlDenied, match='KILL_SWITCH_ACTIVE'):
        preflight(repo, proposal)


def test_audit_chain_valid_and_terminal(repo):
    log = repo.parent / 'events.jsonl'
    d = 'a' * 64
    first = append_journal(log, AUDIT, run_id='RUN-long-0001', event='PREPARED', request_hash=d)
    assert first['seq'] == 1
    second = append_journal(log, AUDIT, run_id='RUN-long-0001', event='BLOCKED', request_hash=d)
    assert second['seq'] == 2
    with pytest.raises(ControlDenied):
        append_journal(log, AUDIT, run_id='RUN-long-0001', event='PREPARED', request_hash=d)
    assert len(read_journal(log, AUDIT)) == 2


def test_journal_detects_tamper_wrong_key_truncation(repo):
    log = repo.parent / 'events.jsonl'
    append_journal(log, AUDIT, run_id='RUN-long-0001', event='PREPARED', request_hash='b' * 64)
    with pytest.raises(ControlDenied):
        read_journal(log, SECRET)
    content = log.read_bytes()
    log.write_bytes(content[:-3])
    with pytest.raises(ControlDenied):
        read_journal(log, AUDIT)


def test_approval_reuse_blocked_in_journal(repo):
    log = repo.parent / 'events.jsonl'
    append_journal(log, AUDIT, run_id='RUN-long-0001', event='PREPARED', request_hash='b' * 64)
    append_journal(log, AUDIT, run_id='RUN-long-0001', event='APPROVED', request_hash='b' * 64, approval_token_id='e' * 64)
    append_journal(log, AUDIT, run_id='RUN-long-0002', event='PREPARED', request_hash='b' * 64)
    with pytest.raises(ControlDenied):
        append_journal(log, AUDIT, run_id='RUN-long-0002', event='APPROVED', request_hash='b' * 64, approval_token_id='e' * 64)


def test_only_attested_evidence_can_mark_pass(repo):
    log = repo.parent / 'events.jsonl'
    append_journal(log, AUDIT, run_id='RUN-long-0001', event='PREPARED', request_hash='a' * 64)
    with pytest.raises(ControlDenied):
        append_journal(log, AUDIT, run_id='RUN-long-0001', event='VERIFICATION_ATTESTED', request_hash='a' * 64)
    append_journal(log, AUDIT, run_id='RUN-long-0001', event='VERIFICATION_ATTESTED', request_hash='a' * 64, evidence_hash='f' * 64)
    assert read_journal(log, AUDIT)[-1]['payload']['event'] == 'VERIFICATION_ATTESTED'


def test_journal_lock_does_not_force_break(repo):
    log = repo.parent / 'events.jsonl'
    lock = repo.parent / 'events.jsonl.lock'
    lock.write_text('busy')
    with pytest.raises(ControlDenied, match='Journal busy'):
        append_journal(log, AUDIT, run_id='RUN-long-0001', event='PREPARED', request_hash='a' * 64)


def test_usage_meter_never_auto_executes():
    cap = {'max_attempts': 2, 'max_cost_usd': 5, 'max_runtime_seconds': 100}
    assert check_budget(cap, Usage(2, 100, 5))['can_continue']
    assert not check_budget(cap, Usage(3, 10, 1))['can_continue']
    assert not check_budget(cap, Usage(1, 101, 1))['can_continue']
    assert not check_budget(cap, Usage(1, 1, 5.01))['can_continue']
    with pytest.raises(ControlDenied):
        check_budget(cap, Usage(1, 1, float('nan')))


def test_v2_only_unsigned_history_never_accepted(repo, proposal):
    artifact = repo.parent / 'evidence'
    artifact.mkdir()
    (artifact / 'summary.json').write_text('{"overall":"PASS","rounds_passed":3}')
    manifest = repo.parent / 'unsigned.json'
    manifest.write_text('{}')
    res = verify_p41_evidence(artifact_dir=artifact, manifest=manifest,
        profile=repo / '.agent/execution-profiles.yaml',run_id=123,
        commit_sha=COMMIT,model_id='deepseek-chat',key_id='k',secret=SECRET.encode())
    assert res['status'] == 'BLOCKED' and not res['independent_verified']


def _capture_cli(args):
    s = StringIO()
    with redirect_stdout(s):
        code = main(args)
    return code, json.loads(s.getvalue())


def test_cli_inspect_preflight_and_denial(repo, proposal):
    req = repo.parent / 'proposal.json'
    req.write_text(json.dumps(proposal))
    code, payload = _capture_cli(['inspect', '--repo-root', str(repo)])
    assert code == 0 and payload['status'] == 'READ_ONLY_DISCOVERY'
    common = ['--repo-root', str(repo), '--trusted-profile', '.agent/execution-profiles.yaml', '--request', str(req)]
    code, payload = _capture_cli(['preflight', *common])
    assert code == 0 and payload['decision'] == 'SCOPE_PRECHECK_OK'
    proposal['paths'] = ['server/src/test/hack.java']
    req.write_text(json.dumps(proposal))
    code, payload = _capture_cli(['preflight', *common])
    assert code == 2 and payload['decision'] == 'BLOCKED'


def test_cli_disallows_unverified_approval_journal(repo, proposal, monkeypatch):
    monkeypatch.setenv('AGENTFORGE_V4_AUDIT_KEY', AUDIT)
    log = repo.parent / 'events.jsonl'
    code, result = _capture_cli(['journal', '--file', str(log), '--event', 'PREPARED',
                                '--run-id', proposal['run_id'], '--request-hash', 'a' * 64])
    assert code == 0
    code, result = _capture_cli(['verify-journal', '--file', str(log)])
    assert code == 0 and result['count'] == 1
    with pytest.raises(SystemExit):
        main(['journal', '--file', str(log), '--event', 'APPROVED',
              '--run-id', proposal['run_id'], '--request-hash', 'a' * 64])


def test_cli_manual_approval_record_operator_cannot_fake_scope(repo, proposal, monkeypatch):
    monkeypatch.setenv('AGENTFORGE_V4_AUDIT_KEY', AUDIT)
    monkeypatch.setenv('AGENTFORGE_V4_APPROVAL_KEY', SECRET)
    a = high_risk(repo, proposal)
    req = repo.parent / 'proposal.json'
    req.write_text(json.dumps(proposal))
    common = ['--repo-root', str(repo), '--trusted-profile', '.agent/execution-profiles.yaml', '--request', str(req)]
    code, failure = _capture_cli(['approve', *common, '--operator', 'owner-001', '--confirm', 'no'])
    assert code == 2
    code, approved = _capture_cli(['approve', *common, '--operator', 'owner-001', '--confirm', 'HUMAN_APPROVES_EXISTING_SCOPE'])
    assert code == 0 and 'approval_token' in approved
    token_path = repo.parent / 'token.json'
    token_path.write_text(json.dumps({'approval_token': approved['approval_token']}))
    log = repo.parent / 'events.jsonl'
    append_journal(log, AUDIT, run_id=proposal['run_id'], event='PREPARED', request_hash=a.request_hash)
    code, recorded = _capture_cli(['record-approved', *common, '--token-file', str(token_path), '--file', str(log)])
    assert code == 0 and recorded['journal']['event'] == 'APPROVED'
    code, failed = _capture_cli(['record-approved', *common, '--token-file', str(token_path), '--file', str(log)])
    assert code == 2 and failed['status'] == 'BLOCKED'


def test_dag_order_and_disjoint_agents(repo, proposal):
    from agentforge.v4 import propose_batch
    database = copy.deepcopy(proposal)
    database.update(task_id='TASK-000002', agent='database', paths=['database/migrations/V2.sql'])
    manifest = {'schema': 'agentforge.control.batch.v4/1',
                'max_concurrent': 2, 'max_total_cost_usd': 10,
                'tasks': [{'request': proposal, 'depends_on': []},
                          {'request': database, 'depends_on': ['TASK-000001']}]}
    result = propose_batch(repo, '.agent/execution-profiles.yaml', manifest)
    assert result['status'] == 'AWAITING_HUMAN_APPROVAL'
    assert result['waves'] == [['TASK-000001'], ['TASK-000002']]
    assert result['executed'] is False


def test_dag_conflicting_writes_without_order_are_denied(repo, proposal):
    from agentforge.v4 import propose_batch
    conflict = copy.deepcopy(proposal)
    conflict['task_id'] = 'TASK-000002'
    manifest = {'schema': 'agentforge.control.batch.v4/1', 'max_concurrent': 2,
                'max_total_cost_usd': 10,
                'tasks': [{'request': proposal, 'depends_on': []},
                          {'request': conflict, 'depends_on': []}]}
    with pytest.raises(ControlDenied, match='Conflicting file writes'):
        propose_batch(repo, '.agent/execution-profiles.yaml', manifest)


def test_dag_disjoint_agent_parallel_waves(repo, proposal):
    from agentforge.v4 import propose_batch
    database = copy.deepcopy(proposal)
    database.update(task_id='TASK-000002', agent='database', paths=['database/migrations/V2.sql'])
    manifest = {'schema': 'agentforge.control.batch.v4/1', 'max_concurrent': 2,
                'max_total_cost_usd': 10,
                'tasks': [{'request': proposal, 'depends_on': []},
                          {'request': database, 'depends_on': []}]}
    assert propose_batch(repo, '.agent/execution-profiles.yaml', manifest)['waves'] == [['TASK-000001','TASK-000002']]


def test_dag_cycle_and_missing_dependency(repo, proposal):
    from agentforge.v4 import propose_batch
    other = copy.deepcopy(proposal)
    other.update(task_id='TASK-000002', paths=['server/src/main/java/B.java'])
    root = {'schema': 'agentforge.control.batch.v4/1', 'max_concurrent': 2,
            'max_total_cost_usd': 10,
            'tasks': [{'request': proposal, 'depends_on': ['TASK-000002']},
                      {'request': other, 'depends_on': ['TASK-000001']}]}
    with pytest.raises(ControlDenied, match='Cycle'):
        propose_batch(repo, '.agent/execution-profiles.yaml', root)
    root['tasks'][1]['depends_on'] = ['TASK-DOES-NOT-EXIST']
    with pytest.raises(ControlDenied, match='missing dependency'):
        propose_batch(repo, '.agent/execution-profiles.yaml', root)


def test_dag_cost_caps(repo, proposal):
    from agentforge.v4 import propose_batch
    root = {'schema': 'agentforge.control.batch.v4/1', 'max_concurrent': 2,
            'max_total_cost_usd': 4,
            'tasks': [{'request': proposal, 'depends_on': []}]}
    with pytest.raises(ControlDenied, match='cost budget exceeded'):
        propose_batch(repo, '.agent/execution-profiles.yaml', root)


def test_dag_cross_commit_is_blocked(repo, proposal):
    from agentforge.v4 import propose_batch
    other = copy.deepcopy(proposal)
    other.update(task_id='TASK-000002', commit='b'*40, paths=['server/src/main/java/Another.java'])
    root = {'schema': 'agentforge.control.batch.v4/1', 'max_concurrent': 2,
            'max_total_cost_usd': 10,
            'tasks': [{'request': proposal, 'depends_on': []},
                      {'request': other, 'depends_on': []}]}
    with pytest.raises(ControlDenied, match='Cross-project'):
        propose_batch(repo, '.agent/execution-profiles.yaml', root)


def test_release_gate_is_advisory_only():
    from agentforge.v4.release import assess_maturity
    matrix = {'3.11': {'status': 'PASS', 'runs_required': 3, 'runs_passed': 3},
              '3.12': {'status': 'PASS', 'runs_required': 3, 'runs_passed': 3}}
    fake_live = {'status': 'SYNTHETIC_V3_P2_EVIDENCE_VERIFIED', 'independent_verified': True}
    candidate = assess_maturity(offline_matrix=matrix, synthetic_live=fake_live,
                                project_behavior={'independent_verified': True, 'scope': 'REAL_PROJECT_BEHAVIOR'})
    assert candidate['status'] == 'V4_ACCEPTANCE_CANDIDATE_NEEDS_HUMAN_REVIEW'
    assert not candidate['production_release_authorized'] and not candidate['authenticated_by_this_function']
    blocked = assess_maturity(offline_matrix={}, synthetic_live=None, project_behavior=None)
    assert blocked['status'] == 'BLOCKED' and len(blocked['issues']) == 4


def test_django_sample_profile_admits_only_services_file(tmp_path):
    import yaml
    root = tmp_path / 'django'
    (root / '.agent').mkdir(parents=True)
    (root / 'apps/orders').mkdir(parents=True)
    (root / 'manage.py').write_text('')
    (root / 'pyproject.toml').write_text('')
    source = Path(__file__).resolve().parents[1] / 'examples/v4/django_execution_profiles.yaml'
    yaml.safe_load(source.read_text('utf-8'))
    (root / '.agent/execution-profiles.yaml').write_text(source.read_text('utf-8'))
    data = json.loads((Path(__file__).resolve().parents[1] / 'examples/v4/django_request.json').read_text('utf-8'))
    good = evaluate_request(root, '.agent/execution-profiles.yaml', data)
    assert good.decision == 'SCOPE_PRECHECK_OK' and 'django' in good.observed_adapters
    data['paths'] = ['apps/orders/migrations/0001_initial.py']
    assert evaluate_request(root, '.agent/execution-profiles.yaml', data).decision == 'BLOCKED'


def test_dag_rejects_nonstring_dependency(repo, proposal):
    from agentforge.v4 import propose_batch
    root = {'schema': 'agentforge.control.batch.v4/1', 'max_concurrent': 2,
            'max_total_cost_usd': 10,
            'tasks': [{'request': proposal, 'depends_on': [{'invalid': 'id'}]}]}
    with pytest.raises(ControlDenied, match='Invalid dependency list'):
        propose_batch(repo, '.agent/execution-profiles.yaml', root)


def test_v4_modules_have_no_production_execution_interfaces():
    source = Path(__file__).resolve().parents[1] / 'src/agentforge/v4'
    for file in source.glob('*.py'):
        text = file.read_text('utf-8')
        assert 'subprocess.run(' not in text
        assert 'shell=True' not in text
        assert 'git push' not in text
    actions = (Path(__file__).resolve().parents[1] /
               '.github/workflows/agentforge-v40-control-offline.yml').read_text('utf-8')
    assert 'contents: read' in actions
    assert 'workflow_dispatch:' in actions
    assert 'AGENTFORGE_LLM_API_KEY' not in actions
    assert 'run_v20_stability.py' not in actions
