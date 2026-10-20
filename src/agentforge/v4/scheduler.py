"""Deterministic multi-Agent DAG planning without executing a single task.

Runs on one repository/commit/Run ID. All task proposals are checked against
trusted profiles before dependency scheduling. Conflicting concurrent tasks
are serialized (if dependency exists), otherwise rejected.
"""
from __future__ import annotations
from typing import Any
from .core import ControlDenied, evaluate_request


def propose_batch(repo_root, profile_rel: str, manifest: dict[str, Any]) -> dict:
    if not isinstance(manifest, dict) or set(manifest) != {'schema', 'max_concurrent', 'max_total_cost_usd', 'tasks'}:
        raise ControlDenied('Unexpected DAG manifest fields')
    if manifest['schema'] != 'agentforge.control.batch.v4/1':
        raise ControlDenied('Unsupported DAG format')
    maximum = manifest['max_concurrent']
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ControlDenied('Only 1..4 concurrent tasks allowed')
    limit = manifest['max_total_cost_usd']
    if type(limit) not in (int, float) or not 0 <= limit <= 100:
        raise ControlDenied('Invalid total cost limit')
    items = manifest['tasks']
    if not isinstance(items, list) or not 1 <= len(items) <= 40:
        raise ControlDenied('1..40 tasks required')
    tasks = {}
    project_commit_run = set()
    cost = 0.0
    for item in items:
        if not isinstance(item, dict) or set(item) != {'request', 'depends_on'}:
            raise ControlDenied('Task wrapper must have request and depends_on')
        request = item['request']
        if not isinstance(request, dict):
            raise ControlDenied('Task request invalid')
        task_id = request.get('task_id')
        if task_id in tasks:
            raise ControlDenied('Duplicate task IDs')
        dependencies = item['depends_on']
        if (not isinstance(dependencies, list) or len(dependencies) > 39 or
            not all(isinstance(d, str) for d in dependencies) or len(set(dependencies)) != len(dependencies)):
            raise ControlDenied('Invalid dependency list')
        admission = evaluate_request(repo_root, profile_rel, request)
        tasks[task_id] = {'request': request, 'depends_on': dependencies, 'admission': admission}
        project_commit_run.add((request['project'], request['commit'], request['run_id']))
        cost += float(request['budget']['max_cost_usd'])
    if len(project_commit_run) != 1:
        raise ControlDenied('Cross-project, cross-commit or cross-run DAG is forbidden')
    if cost > limit or cost != cost:
        raise ControlDenied('Batch cost budget exceeded')
    for task_id, task in tasks.items():
        if task_id in task['depends_on'] or any(d not in tasks for d in task['depends_on']):
            raise ControlDenied('Self/missing dependency')
        if task['admission'].decision == 'BLOCKED':
            return {'status': 'BLOCKED', 'issues': ['SCOPE_DENIED:' + task_id],
                    'waves': [], 'executed': False, 'production_release_authorized': False}
    # Build reachability (dependents) for conflict checks and cycle prevention.
    visiting, done, ancestors = set(), set(), {}
    def visit(n):
        if n in visiting:
            raise ControlDenied('Cycle in task dependency graph')
        if n in done:
            return ancestors[n]
        visiting.add(n)
        parents = set(tasks[n]['depends_on'])
        for p in list(parents):
            parents.update(visit(p))
        visiting.remove(n)
        done.add(n)
        ancestors[n] = parents
        return parents
    for tid in tasks:
        visit(tid)
    ids = sorted(tasks)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            pa, pb = set(tasks[a]['admission'].eligible_paths), set(tasks[b]['admission'].eligible_paths)
            if pa & pb and a not in ancestors[b] and b not in ancestors[a]:
                raise ControlDenied('Conflicting file writes require explicit dependency ordering: ' + a + '/' + b)
    remaining = set(ids)
    waves = []
    completed = set()
    while remaining:
        ready = sorted(t for t in remaining if set(tasks[t]['depends_on']) <= completed)
        if not ready:
            raise ControlDenied('Unable to schedule dependency graph')
        wave, busy_agents = [], set()
        for tid in ready:
            agent = tasks[tid]['request']['agent']
            if agent in busy_agents:
                continue
            wave.append(tid)
            busy_agents.add(agent)
            if len(wave) == maximum:
                break
        waves.append(wave)
        remaining.difference_update(wave)
        completed.update(wave)
    approval = any(t['admission'].decision == 'AWAITING_HUMAN_APPROVAL' for t in tasks.values())
    return {'status': 'AWAITING_HUMAN_APPROVAL' if approval else 'SCHEDULE_PROPOSAL_ONLY',
            'waves': waves, 'total_cost_cap_usd': cost,
            'requires_task_approval': [tid for tid in ids if tasks[tid]['admission'].decision == 'AWAITING_HUMAN_APPROVAL'],
            'executed': False, 'production_release_authorized': False,
            'note': 'A schedule is not permission to run tasks. Existing V2 write/sandbox checks remain mandatory.'}
