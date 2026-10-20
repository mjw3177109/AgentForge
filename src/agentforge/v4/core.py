"""AgentForge V4 deterministic control plane (no model or shell execution).

This module intentionally has no capability to write application source, execute
verification commands, merge pull requests or deploy. All authority is derived
from a trusted V2 execution-profile file, never a model-generated task.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

SCHEMA = 'agentforge.control.v4/1'
SHA40 = re.compile(r'[0-9a-f]{40}\Z')
AGENT = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')
TASK = re.compile(r'TASK-[A-Za-z0-9._:-]{1,100}\Z')
WORKSPACE = re.compile(r'[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,100}\Z')
ALLOWED_ACTIONS = frozenset({'PROPOSE_EDIT', 'REQUEST_VERIFICATION'})
RISK = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2, 'CRITICAL': 3}


class ControlDenied(ValueError):
    """A trusted boundary is not established; stop rather than guess."""


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha256(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def _require_string(value: Any, label: str, *, max_len: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_len or '\x00' in value:
        raise ControlDenied(f'{label} must be a nonempty bounded string')
    return value


def strict_path(value: Any, *, allow_glob: bool = False) -> str:
    """Reject traversal, absolute paths, non-canonical and dangerous names."""
    raw = _require_string(value, 'path', max_len=400)
    if (raw.startswith('/') or '\\' in raw or ':' in raw or raw.startswith('~') or
        '//' in raw or raw.endswith('/') or any(x in ('.', '..', '') for x in raw.split('/'))):
        raise ControlDenied('Non-canonical/escaping path')
    segments = raw.split('/')
    if segments[0] in ('.git', '.github') or any(x == '.git' for x in segments):
        raise ControlDenied('Git metadata and CI policy are maintainer-owned')
    if not allow_glob and any(x in raw for x in '*?[]'):
        raise ControlDenied('Proposed target must be an exact file path')
    if allow_glob:
        if any('?' in p or '[' in p or ']' in p or ('*' in p and p != '**') for p in segments):
            raise ControlDenied('Only literal directory/** tree patterns are accepted')
        if segments[-1] != '**' and '**' in segments:
            raise ControlDenied('Glob only at end')
    return str(PurePosixPath(raw))


def _guard_file(root: Path, relative: str, *, allow_absent: bool = False) -> Path:
    path = root
    for segment in relative.split('/'):
        path = path / segment
        if path.is_symlink():
            raise ControlDenied('Symlink in target or parent path')
    if not allow_absent and not path.is_file():
        raise ControlDenied(f'Required trusted file missing: {relative}')
    if path.exists():
        if not path.is_file():
            raise ControlDenied('Nonregular target')
        st = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ControlDenied('Linked/nonregular target')
    return path


def _scope_contains(path: str, rule: str) -> bool:
    # Deliberately narrower than fnmatch: this code NEVER enlarges a V2 scope.
    if rule == path:
        return True
    if rule.endswith('/**'):
        parent = rule[:-3]
        return bool(parent) and path.startswith(parent + '/')
    return False


def _scope_match(path: str, rules: list[str]) -> bool:
    return any(_scope_contains(path, rule) for rule in rules)


def _manifest(value: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != allowed:
        raise ControlDenied(f'{label} fields invalid (fail-closed)')
    return value


@dataclass(frozen=True)
class AdapterObservation:
    stack: str
    markers: tuple[str, ...]
    suggested_checks: tuple[tuple[str, ...], ...]
    executable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_stacks(repo_root: Path) -> list[AdapterObservation]:
    """Read-only discovery. Suggestions are NEVER executed here."""
    root = Path(repo_root).resolve(strict=True)
    specs = (
        ('django', ('manage.py',), (('python', 'manage.py', 'check'),)),
        ('spring', ('pom.xml',), (('mvn', '-q', 'test'),)),
        ('spring-module', ('server/pom.xml',), (('mvn', '-q', '-f', 'server/pom.xml', 'test'),)),
        ('vite', ('vite.config.js', 'package.json'), (('npm', 'run', 'build'),)),
        ('vite-module', ('admin-web/vite.config.js', 'admin-web/package.json'), (('npm', '--prefix', 'admin-web', 'run', 'build'),)),
        ('node', ('package.json',), (('npm', 'test'),)),
        ('python', ('pyproject.toml',), (('python', '-m', 'pytest', '-q'),)),
    )
    observed = []
    for stack, markers, checks in specs:
        if all(_guard_file(root, p, allow_absent=True).is_file() for p in markers):
            observed.append(AdapterObservation(stack, markers, checks))
    return observed


@dataclass(frozen=True)
class TrustedScope:
    agent: str
    read: tuple[str, ...]
    write: tuple[str, ...]
    deny: tuple[str, ...]


def read_profiles(repo_root: Path, relative: str) -> tuple[str, dict[str, TrustedScope]]:
    """Parse trusted V2 profiles without accepting a task-supplied policy."""
    root = Path(repo_root).resolve(strict=True)
    rel = strict_path(relative)
    raw = _guard_file(root, rel).read_bytes()
    if len(raw) > 1024 * 1024:
        raise ControlDenied('Profile too large')
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ControlDenied('Unparseable trusted profile') from exc
    if not isinstance(doc, dict) or not isinstance(doc.get('agents'), dict) or not doc['agents']:
        raise ControlDenied('Trusted profile requires agents')
    profiles = {}
    for name, profile in doc['agents'].items():
        if not isinstance(name, str) or not AGENT.fullmatch(name) or not isinstance(profile, dict):
            raise ControlDenied('Invalid agent profile')
        scopes = []
        for key in ('read_scope', 'write_scope', 'deny_scope'):
            arr = profile.get(key)
            if not isinstance(arr, list) or not all(isinstance(x, str) for x in arr):
                raise ControlDenied(f'Invalid {name}.{key}')
            # V4 deliberately does not accept patterns beyond directory/** or exact file.
            scopes.append(tuple(strict_path(x, allow_glob=True) for x in arr))
        profiles[name] = TrustedScope(name, *scopes)
    return hashlib.sha256(raw).hexdigest(), profiles


def classify_path(path: str) -> str:
    tokens = set(re.split(r'[/._-]', path.lower()))
    if tokens & {'prod', 'production', 'deploy', 'release', 'secrets', 'secret', 'auth', 'authentication', 'permission', 'permissions', 'billing', 'payment', 'payments', 'security'}:
        return 'CRITICAL'
    if path.endswith(('.sql', '.yaml', '.yml')) or tokens & {'migration', 'migrations', 'database', 'schema', 'config'}:
        return 'HIGH'
    if tokens & {'tests', 'test', 'docker', 'infra'}:
        return 'MEDIUM'
    return 'LOW'


@dataclass(frozen=True)
class Admission:
    decision: str
    reason_codes: tuple[str, ...]
    risk: str
    request_hash: str
    profile_hash: str
    observed_adapters: tuple[str, ...]
    eligible_paths: tuple[str, ...]
    verified: bool = False
    executed: bool = False
    permission_expanded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_request(repo_root: Path, profile_rel: str, request: dict[str, Any]) -> Admission:
    """Zero execution: approve only an in-scope *proposal*, not a code write."""
    root = Path(repo_root).resolve(strict=True)
    stop = _guard_file(root, '.agent/v4/KILL_SWITCH', allow_absent=True)
    if stop.exists():
        raise ControlDenied('KILL_SWITCH_ACTIVE: operator must review and remove it')
    required = {'schema', 'project', 'commit', 'run_id', 'task_id', 'agent', 'action', 'paths', 'budget'}
    _manifest(request, required, 'request')
    if request['schema'] != SCHEMA:
        raise ControlDenied('Unsupported control protocol version')
    project = _require_string(request['project'], 'project', max_len=181)
    if not WORKSPACE.fullmatch(project) or any(p in {'.', '..'} for p in project.split('/')):
        raise ControlDenied('Project identifier must be owner/repository')
    if not isinstance(request['commit'], str) or not SHA40.fullmatch(request['commit']):
        raise ControlDenied('Commit must be full 40-char lower-case SHA')
    if not isinstance(request['run_id'], str) or not re.fullmatch(r'[a-zA-Z0-9-]{8,100}', request['run_id']):
        raise ControlDenied('Run ID must be an externally assigned stable identifier')
    if not isinstance(request['task_id'], str) or not TASK.fullmatch(request['task_id']):
        raise ControlDenied('Bad task ID')
    if not isinstance(request['agent'], str) or not AGENT.fullmatch(request['agent']):
        raise ControlDenied('Bad agent')
    if not isinstance(request['action'], str) or request['action'] not in ALLOWED_ACTIONS:
        raise ControlDenied('Unsupported action; no implicit write/deploy authorization')
    paths = request['paths']
    if not isinstance(paths, list) or not paths or len(paths) > 100:
        raise ControlDenied('Paths must be a bounded nonempty list')
    _manifest(request['budget'], {'max_attempts', 'max_cost_usd', 'max_runtime_seconds'}, 'budget')
    budget = request['budget']
    if type(budget['max_attempts']) is not int or budget['max_attempts'] not in range(1, 4):
        raise ControlDenied('Repair attempt budget must be 1..3')
    if type(budget['max_runtime_seconds']) is not int or not 1 <= budget['max_runtime_seconds'] <= 3600:
        raise ControlDenied('Runtime budget 1..3600')
    if type(budget['max_cost_usd']) not in (int, float) or not 0 <= budget['max_cost_usd'] <= 100:
        raise ControlDenied('Model cost budget 0..100 dollars')
    # Numeric NaN rejected by canonical serialization.
    digest = sha256(request)
    profile_hash, scopes = read_profiles(root, profile_rel)
    if request['agent'] not in scopes:
        raise ControlDenied('Unknown agent (cannot invent profile)')
    scope = scopes[request['agent']]
    reasons = []
    normalized = []
    risk = 'LOW'
    for item in paths:
        try:
            path = strict_path(item)
            _guard_file(root, path, allow_absent=True)
            if path in normalized:
                raise ControlDenied('Duplicate path')
            if _scope_match(path, list(scope.deny)):
                raise ControlDenied('Explicit trusted deny')
            if not _scope_match(path, list(scope.write)):
                raise ControlDenied('Not inside trusted write scope')
            # Conservative subset of V2's policy; V2 will recheck at execution.
            normalized.append(path)
            current = classify_path(path)
            if RISK[current] > RISK[risk]:
                risk = current
        except ControlDenied:
            reasons.append('SCOPE_OR_PATH_DENIED')
    if reasons:
        decision = 'BLOCKED'
    elif request['action'] == 'REQUEST_VERIFICATION':
        decision = 'PROPOSAL_ONLY'
    elif risk in ('HIGH', 'CRITICAL'):
        decision = 'AWAITING_HUMAN_APPROVAL'
        reasons.append('RISK_REQUIRES_APPROVAL')
    else:
        decision = 'SCOPE_PRECHECK_OK'
    adapters = tuple(a.stack for a in detect_stacks(root))
    return Admission(decision, tuple(sorted(set(reasons))), risk, digest, profile_hash,
                     adapters, tuple(normalized))
