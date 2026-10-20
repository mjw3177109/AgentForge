"""V3 P4.1 safety gates; no external model calls or GitHub mutations."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agentforge.acceptance_p41 import assess_canary_round, assess_canary_summary
from agentforge.evidence_v3 import EXPECTED_V20_GATES, collect_v20, attest
from test_v3_evidence import create_fixture, SECRET, COMMIT, MODEL, RUN_ID
from test_v3_p2_installer import fake_repo


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def good_record(index=1):
    return {
        'round': index, 'stage': 'passed', 'status': 'PASS',
        'review_status': 'APPROVE', 'v3_safe_repair_flag_injected': True,
        'initial_agents': ['database', 'backend', 'miniapp', 'admin'],
        'gates': [{'name': name, 'status': 'PASS', 'exit_code': 0}
                  for name in EXPECTED_V20_GATES],
    }


def summary(records):
    return {'overall': 'PASS', 'rounds_required': 3, 'rounds_passed': 3,
            'results': records, 'v3_canary_mode': 'V3_P2_SAFE_REPAIR_OPT_IN'}


def test_3_round_canary_is_candidate_not_authenticated_release():
    rows = [good_record(i) for i in [1, 2, 3]]
    result = assess_canary_summary(summary(rows), rows)
    assert result['status'] == 'V3_P2_CANARY_3_OF_3_PASS'
    assert result['authenticated'] is False
    assert result['requires_independent_p1_attestation'] is True
    assert result['production_release_authorized'] is False


@pytest.mark.parametrize('change,expected', [
    (lambda x: x.update(status='FAIL'), 'ROUND_NOT_PASSED'),
    (lambda x: x.update(v3_safe_repair_flag_injected=False), 'V3_P2_OPT_IN_MARKER_MISSING'),
    (lambda x: x.update(review_status='BLOCKED'), 'REVIEWER_NOT_APPROVE'),
    (lambda x: x['initial_agents'].pop(), 'FOUR_AGENT_EVIDENCE_MISSING'),
    (lambda x: x['gates'].pop(), 'INDEPENDENT_GATE_COVERAGE_MISMATCH'),
    (lambda x: x['gates'][0].update(status='SKIP'), 'INDEPENDENT_GATE_FAILED'),
    (lambda x: x['gates'][0].update(exit_code=1), 'INDEPENDENT_GATE_FAILED'),
])
def test_gate_bypass_attempts_fail_closed(change, expected):
    x = good_record()
    change(x)
    found = assess_canary_round(x, flag_was_injected=x['v3_safe_repair_flag_injected'])
    assert found['status'] == 'FAIL' and expected in found['issues']


@pytest.mark.parametrize('alteration', ['round_fail', 'incomplete', 'missing_mode', 'forged_summary', 'reordered'])
def test_3_round_summary_forgery_blocked(alteration):
    rows = [good_record(i) for i in [1, 2, 3]]
    s = summary(rows)
    if alteration == 'round_fail':
        rows[0]['status'] = 'FAIL'
    elif alteration == 'incomplete':
        rows.pop()
    elif alteration == 'missing_mode':
        s.pop('v3_canary_mode')
    elif alteration == 'forged_summary':
        s['rounds_passed'] = 2
    elif alteration == 'reordered':
        rows.reverse()
    assert assess_canary_summary(s, rows)['status'] == 'BLOCKED'


def _prepare_signed_v3_fixture(tmp_path, add_mode=True):
    artifacts, profile = create_fixture(tmp_path)
    if add_mode:
        rows = []
        for i in [1, 2, 3]:
            path = artifacts / f'round_{i:02d}' / 'v20_result.json'
            record = json.loads(path.read_text())
            record.update({'v3_safe_repair_flag_injected': True})
            path.write_text(json.dumps(record), encoding='utf-8')
            rows.append(record)
        path = artifacts / 'summary.json'
        doc = json.loads(path.read_text())
        doc.update({'results': rows, 'v3_canary_mode': 'V3_P2_SAFE_REPAIR_OPT_IN'})
        path.write_text(json.dumps(doc), encoding='utf-8')
    sig = attest(collect_v20(artifact_dir=artifacts, run_id=RUN_ID,
                             commit_sha=COMMIT, model_id=MODEL,
                             trusted_profile=profile), secret=SECRET, key_id='p41-test')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(sig), encoding='utf-8')
    return artifacts, profile, manifest


def test_signed_v2_3_of_3_not_equal_v3_p2_attestation(tmp_path):
    verifier = load_script('v3_p41_verify_test', ROOT / 'scripts/v3_p41_verify.py')
    root, profile, manifest = _prepare_signed_v3_fixture(tmp_path, add_mode=False)
    result = verifier.verify(root, profile, manifest, run_id=RUN_ID,
                             commit=COMMIT, model=MODEL, key_id='p41-test', secret=SECRET)
    assert result['status'] == 'BLOCKED'


def test_signed_v3_canary_still_disallows_release(tmp_path):
    verifier = load_script('v3_p41_verify_test2', ROOT / 'scripts/v3_p41_verify.py')
    root, profile, manifest = _prepare_signed_v3_fixture(tmp_path)
    result = verifier.verify(root, profile, manifest, run_id=RUN_ID,
                             commit=COMMIT, model=MODEL, key_id='p41-test', secret=SECRET)
    assert result['status'] == 'P41_V3_P2_ATTESTED_PASS'
    assert result['automated_merge_authorized'] is False
    assert result['production_release_authorized'] is False
    # Tamper with signed V3 opt-in evidence after P1 signing.
    doc = json.loads((root / 'round_02/v20_result.json').read_text())
    doc['v3_safe_repair_flag_injected'] = False
    (root / 'round_02/v20_result.json').write_text(json.dumps(doc))
    assert verifier.verify(root, profile, manifest, run_id=RUN_ID, commit=COMMIT,
                           model=MODEL, key_id='p41-test', secret=SECRET)['status'] == 'BLOCKED'


def test_live_runner_cannot_upgrade_missing_p2_marker(tmp_path, monkeypatch):
    runner = load_script('v3_p41_live_test', ROOT / 'scripts/v3_p41_live_acceptance.py')
    from agentforge.evidence_v3 import EXPECTED_V20_GATES
    class FakeV20:
        @staticmethod
        def assess_result(payload, exit_code):
            return ('passed', 'ok') if exit_code == 0 else ('execution', 'failed')
        @staticmethod
        def verify_snapshot(snapshot, folder, index):
            return [{'name': n, 'status': 'PASS', 'exit_code': 0} for n in EXPECTED_V20_GATES]
        @staticmethod
        def classify_failure(stage, detail):
            return 'FRAMEWORK_OR_ENVIRONMENT'
    def fake_run(argv, **kwargs):
        folder = Path(kwargs['env']['AGENTFORGE_BENCHMARK_ARTIFACT_DIR'])
        (folder / 'generated-repo').mkdir(parents=True)
        assert kwargs['shell'] is False
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status': 'SUCCESS', 'review': {'status': 'APPROVE'}}), stderr='')
    monkeypatch.setattr(runner.subprocess, 'run', fake_run)
    got = runner.run_round(1, tmp_path, 1200, repo=ROOT, v20=FakeV20())
    assert got['status'] == 'FAIL'
    assert got['stage'] == 'p2_not_executed'
    assert got['v3_safe_repair_flag_injected'] is False


def test_benchmark_flag_injected_only_into_live_cli(monkeypatch):
    fake_hardened = SimpleNamespace()
    intercepted = []
    def normal_run(*args, **kwargs):
        intercepted.append(args)
        return 0
    fake_hardened.base = SimpleNamespace(run=normal_run)
    monkeypatch.setitem(sys.modules, 'run_v18_live_autonomous_benchmark_hardened', fake_hardened)
    module = load_script('v3_p41_hardened_test', ROOT / 'scripts/v3_p41_hardened_benchmark.py')
    record = module.enable_canary()
    fake_hardened.base.run('git', 'status')
    fake_hardened.base.run('agentforge', 'autonomous-live', 'request')
    assert intercepted[0] == ('git', 'status')
    assert intercepted[1] == ('agentforge', 'autonomous-live', 'request', '--v3-safe-repair')
    assert record['invoked'] is True


def test_audit_blocks_non_v3_or_unreviewed_baseline(tmp_path):
    script = load_script('v3_p41_audit_test', ROOT / 'scripts/v3_p41_audit.py')
    subprocess.run(['git', 'init', '-q', tmp_path], check=True)
    got = script.audit(tmp_path)
    assert got['status'] == 'BLOCKED'
    assert 'NOT_AN_ISOLATED_V3_BRANCH' in got['issues']
    assert 'V20_REVIEWED_BASELINE_NOT_ANCESTOR' in got['issues'] or 'NO_VALID_GIT_HEAD' in got['issues']


def test_workflow_manual_read_only_secret_split():
    flow = yaml.load((ROOT / '.github/workflows/agentforge-v30-p41-real-integration.yml').read_text(),
                     Loader=yaml.BaseLoader)
    assert set(flow['on']) == {'workflow_dispatch'}
    assert flow['permissions'] == {'contents': 'read'}
    assert 'live' in flow['jobs'] and 'independent-attestation' in flow['jobs']
    assert 'AGENTFORGE_V3_EVIDENCE_KEY' not in flow['jobs']['live'].get('env', {})
    assert 'AGENTFORGE_LLM_API_KEY' not in flow['jobs']['independent-attestation'].get('env', {})
    assert 'AGENTFORGE_LLM_API_KEY' in flow['jobs']['live']['env']


def test_p2_exact_diff_guard_rejects_extra_changes(fake_repo, monkeypatch):
    from test_v3_p2_installer import installer
    audit = load_script('v3_p41_exact_delta_test', ROOT / 'scripts/v3_p41_audit.py')
    src = fake_repo / 'scripts'
    src.mkdir()
    (src / 'v3_p2_integrate.py').write_bytes((ROOT / 'scripts/v3_p2_integrate.py').read_bytes())
    originals = {
        name: (fake_repo / f'src/agentforge/{name}').read_text('utf-8')
        for name in ('cli.py', 'autonomous.py')
    }

    def fake_git(_repo, *args):
        if args and args[0] == 'show':
            filename = str(args[1]).split('/')[-1]
            return SimpleNamespace(returncode=0, stdout=originals[filename], stderr='')
        raise AssertionError(args)
    monkeypatch.setattr(audit, '_git', fake_git)
    installer.install(installer.plan_integration(fake_repo))
    assert audit.validate_p2_exact_diff(fake_repo) == []
    cli = fake_repo / 'src/agentforge/cli.py'
    cli.write_text(cli.read_text('utf-8') + '\n# malicious unrelated change\n')
    assert any('P2_UNAPPROVED_SOURCE_DELTA' in msg for msg in audit.validate_p2_exact_diff(fake_repo))


def test_p41_integrator_dry_run_then_apply_on_isolated_repo(fake_repo, monkeypatch):
    integrator = load_script('v3_p41_integrator_test', ROOT / 'scripts/v3_p41_install.py')
    sha = integrator._git(fake_repo, 'rev-parse', 'HEAD').stdout.strip()
    monkeypatch.setattr(integrator, 'BASELINE_SHA', sha)
    # The fake P2 module is an untracked placeholder; the pinned P2 ZIP owns
    # this path, and the installer must never replace different existing bytes.
    (fake_repo / 'src/agentforge/repair_v3.py').unlink()
    packages_dir = Path('/mnt/data')
    if not all((packages_dir / name).exists() for name in integrator.PACKAGES):
        pytest.skip('Only runnable with the five previously created local P0-P4 patch ZIPs')
    pre = integrator.install(fake_repo, packages_dir)
    assert pre['status'] == 'DRY_RUN_OK'
    assert '--v3-safe-repair' not in (fake_repo / 'src/agentforge/cli.py').read_text('utf-8')
    applied = integrator.install(fake_repo, packages_dir, apply=True)
    assert applied['status'] == 'APPLIED_UNCOMMITTED'
    assert '--v3-safe-repair' in (fake_repo / 'src/agentforge/cli.py').read_text('utf-8')
    assert (fake_repo / 'src/agentforge/memory_v3.py').is_file()
    assert (fake_repo / '.github/workflows/agentforge-v30-p4-acceptance.yml').is_file()
    with pytest.raises(ValueError, match='TRACKED_WORKTREE_NOT_CLEAN'):
        integrator.install(fake_repo, packages_dir, apply=True)


def test_p41_integrator_refuses_package_mutation_or_missing(fake_repo, monkeypatch, tmp_path):
    integrator = load_script('v3_p41_integrator_test2', ROOT / 'scripts/v3_p41_install.py')
    sha = integrator._git(fake_repo, 'rev-parse', 'HEAD').stdout.strip()
    monkeypatch.setattr(integrator, 'BASELINE_SHA', sha)
    with pytest.raises(ValueError, match='MISSING_PATCH_ZIP'):
        integrator.install(fake_repo, tmp_path)
    subprocess.run(['git', '-C', str(fake_repo), 'switch', '-qc', 'main'], check=True)
    with pytest.raises(ValueError, match='REFUSE_NON_V3_BRANCH'):
        integrator.install(fake_repo, tmp_path)
