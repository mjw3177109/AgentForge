# AgentForge Django Agent Manager V0.3

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

## Ready-to-run demo

An example Django host lives in examples/django_host. It provides the Django admin,
AgentForge dashboard and a simple isolated SQLite host DB. It does not change or
connect to any other project until AGENTFORGE_ALLOWED_ROOTS is explicitly set.

Use this for development / demos only. It is NOT a production-hardened web service.


## V0.2 — bounded queue, human recovery, cautious health metrics

New files: `queue.py`, `recovery.py`, `health.py`, `approvals.py`, new management
commands, new 0002 migration, staff-only dashboard and job details.

Apply migration before running V0.2: `python manage.py migrate agentforge_django`.

Run up to five **AUDIT only** jobs (default):
```bash
python manage.py process_agentforge_queue --max-jobs 5
```

Opt into VERIFY only for trusted code inside an isolated non-production worker:
```bash
python manage.py process_agentforge_queue --max-jobs 2 --include-verify
```
For AUTONOMOUS, additionally pass `--include-autonomous` and satisfy every explicit
per-job approval and global safety flag. No autonomous mode is launched by default.

A unique JobLease prevents concurrent task execution in the same registered project.
If a worker crashes, the lease stays occupied (fail closed). **Only after you
have separately confirmed/stopped the old worker**, recover manually:
```bash
python manage.py recover_agentforge_job <UUID> --confirm-worker-stopped
```
Interrupted RUNNING tasks become BLOCKED, never PASS, and must be resubmitted as a
NEW job. Never run the recovery command while the worker process is still alive.

MutationApproval now stores SHA-256 snapshots of the exact request and project
configuration; changing a request after approval results in BLOCKED. Older approvals
migrated from V0.1 have empty snapshots and therefore fail closed; submit a new job
and create a fresh approval before autonomous execution.

Dashboard 30-day completion rates are simple observed workflow outcomes across
all modes, **not a model stability estimate or evidence of general code quality**.
A static AUDIT result cannot establish business correctness; only an independently
passing VERIFY with business tests may display VERIFIED_TESTS. A zero-test suite
cannot become PASS.

Release, PR push, original project code mutation and production DB access remain
outside the V0.2 automation permission boundary. The worker must run in a sandboxed
VM/container for untrusted target projects. The SQLite demo is for development.


## V0.3 — Agent Control Center (additive UI, no code execution via HTTP)

V0.3 introduces the staff read-only web Control Center, and explicit
superuser-only task submission, human approval and *redacted* evidence export.

### Entry points

- GET `/agentforge/`: fleet health, last 30 tasks, observed activity.
- GET `/agentforge/projects/<int:project_id>/`: project health, worker lock and recent jobs.
- GET/POST `/agentforge/jobs/new/`: superuser-only form that creates a PENDING job.
- GET `/agentforge/jobs/<uuid:job_id>/`: static job status and audit timeline.
- POST `/agentforge/jobs/<uuid:job_id>/approve/`: superuser-only human approval.
- GET `/agentforge/jobs/<uuid:job_id>/evidence.json`: superuser-only sanitized evidence export.

All authenticated staff members have read-only access to general dashboard and
task summaries, but **only an active superuser** can create jobs, approve autonomous
work, or export machine-readable evidence. Use a separate access-controlled host
or alter read permissions if sensitive project names must not be visible to all staff.

A POST to create a job does **not** execute any task. The worker still runs separately
using `run_agentforge_job` or `process_agentforge_queue` from V0.2.
No web endpoint invokes DeepSeek, subprocess, shell commands for task execution,
merges, migrations on target projects, or production deployment. Approval performs a
short read-only Git/policy preflight; it is **not** an Agent execution endpoint.

### Approval flow

A human approval now requires ALL of:

1. Logged-in, active Django superuser with CSRF-protected POST and explicit
   acknowledgement that only a candidate patch is authorized.
2. Job in PENDING / AUTONOMOUS, with no prior approval.
3. `AGENTFORGE_ALLOW_AUTONOMOUS=True`, project autonomous switch enabled,
   project enabled and independent business testing not disabled.
4. Project root within `AGENTFORGE_ALLOWED_ROOTS`; non-symlink profile file.
5. Clean Git working tree, exact base branch at current HEAD, 40-character commit.
6. At least one configured execution profile and every write scope contained
   by the explicitly configured project write scope.

A successful approval pins exact Git HEAD, project settings, job contents and
allowed scopes, with a hash-linked event. A later request/policy change invalidates
the existing approval in the Worker gate, and a second approval cannot silently
replace it. Admin's direct creation of MutationApproval is disabled, so human
preflight cannot be bypassed through its standard Add form.

### Evidence export

JSON contains event sequence/hash information, job result status, sanitized test
success/return codes and optional candidate patch SHA-256. It explicitly excludes
raw source diffs, file contents, stdout/stderr, model prompts, model API keys and
full stack traces; `Cache-Control: no-store` is enforced.

The HTTP interface is not an OS-level security boundary and does not make
VERIFY or AUTONOMOUS execution safe on production hosts. Run target manage.py and
any AI-generated verification commands in a tightly constrained external worker
container or VM. Keep the default demo host settings development-only.

### Verification

Use `python -m django test django_tests --settings=django_tests.settings -v 2`.
V0.3 has test cases covering staff/superuser separation, CSRF, disabled projects,
authorization, approval preflight, idempotence and redacted export. Django+core CI
must PASS before classifying V0.3 as a tested development build.

No paid DeepSeek 3/3 stability testing, production service-level verification, or
secure hostile-code container isolation is claimed in V0.3.
