# AgentForge Django Agent Manager V0.1

## Positioning

Additive installable Django App layered on the existing V2.0 AgentForge core.
Existing business apps, URLs, tables, services and deployment code are not rewritten.
This branch derives from verify/v2.0-stability, NOT the mostly empty main branch.

## Installation into a trusted Django host

1. Install this repository as a package in the same trusted Python environment:
   pip install -e ".[dev]" "Django>=4.2,<6"
2. Add "agentforge_django" to INSTALLED_APPS.
3. Configure AGENTFORGE_ALLOWED_ROOTS = ["/srv/trusted-workspaces"].
4. Keep AGENTFORGE_ALLOW_AUTONOMOUS = False (default).
5. Optionally add path("agentforge/", include("agentforge_django.urls")) to host URLs.
6. Run python manage.py migrate agentforge_django.
7. In Django Admin create a ManagedProject with an **absolute** root_path and explicitly set enabled=True.
8. Add an AgentJob (AUDIT first), then execute from a trusted host terminal:
   python manage.py run_agentforge_job <job-uuid>
9. Review project jobs, structured outcome and hash-linked AuditEvent records in Django Admin.

The console command intentionally has no daemon/queue dependency; use your existing Celery,
RQ, scheduler or worker to invoke the same runner.run_job(pk) in a separate worker process.
Do not call the runner from a web request.

## Modes

- AUDIT: static Python syntax, Django detection, bounded file inspection; never imports
  project code or runs manage.py. Optional AGENTFORGE_READONLY_LLM=True provides a
  non-binding DeepSeek planning report based on sanitized metadata only. This is a
  **static audit**, not a behavioral PASS.
- VERIFY: disposable copy, then independent Django system checks and business tests
  (run_business_tests=True default). No source workspace modifications.
- AUTONOMOUS: **OFF by default** and requires global setting, project setting,
  immutable human approval tied to current git HEAD and exact write scopes, a clean
  trusted Git repository, and a .agent/execution-profiles.yaml policy.
  It delegates planner/executor/reviewer/limited repair to existing V2.0 core, then
  independently runs Django checks/business tests. A passing job stores ONLY a
  candidate patch in AgentJob.result (max 200 KB). It never pushes, merges,
  migrates, deploys or writes the source repo. Status PROPOSED is not production PASS.

### Example project policy (.agent/execution-profiles.yaml)

allowed_verification_executables:
  - python
agents:
  backend:
    context_paths:
      - app/views.py
    read_scope:
      - app/**
    write_scope:
      - app/**
    deny_scope:
      - .git/**
      - .agent/**

Define write_scopes=["app/**"] in ManagedProject and in a human MutationApproval
with base_commit equal to the exact 40-character git HEAD SHA.
The CLI verifier's executable allowlist is independent; never allow shells.
Prefer validation commands in an isolated CI environment.
The core may require stronger evidence contract files / task profiles for your specific project.

### DeepSeek

Set these only in the trusted worker process environment:

AGENTFORGE_LLM_BASE_URL=https://api.deepseek.com
AGENTFORGE_LLM_MODEL=deepseek-chat
AGENTFORGE_LLM_API_KEY=<secret>

Do not put API keys in Django settings, source control, database or job prompts.
Read-only LLM is disabled unless AGENTFORGE_READONLY_LLM=True. Mutating autonomous
mode is disabled unless AGENTFORGE_ALLOW_AUTONOMOUS=True.

## Security and claims

The Python allowlist, copied workspaces and subprocess isolation are **not**
kernel-level security isolation: untrusted manage.py / test code may access network,
filesystem and local services using its OS permissions. Only run VERIFY/AUTONOMOUS
for trusted code in a tightly isolated non-production container/VM with network and
secrets restricted, no production database credentials, and minimum filesystem
permissions. The runner clears common inherited environment credentials but does
not provide a complete sandbox. Job result patches can contain sensitive code;
restrict database and admin access. Use private workers for actual customer code.

Audit hashes detect accidental/unauthorized event edits when checked against an
independent trusted record; they are not immutable against a DB administrator.
Reviewer approval alone never counts as business verification. Missing gates are
recorded as NOT_RUN, never claimed PASS.

## Tests

python -m django check --settings=django_tests.settings
python -m django test django_tests --settings=django_tests.settings -v 2
python -m pytest -q

A 3/3 real DeepSeek multi-round stability PASS for **this Django host** has NOT
been established by the present framework. The original synthetic V2.0
acceptance evidence does not automatically transfer to another Django business app.
