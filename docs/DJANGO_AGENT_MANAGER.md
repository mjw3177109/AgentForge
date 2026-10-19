# AgentForge Django Agent Manager V0.6

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
- VERIFY: offline Docker disposable copy (V0.4 default), then Django system checks and business tests
  (run_business_tests=True default). No source workspace modifications.
- AUTONOMOUS: **OFF by default** (V0.4 also blocks legacy host execution by default) and requires global setting, project setting,
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


## V0.4 — Docker verification, protected worker, 3-round REAL model gate

### Purpose, implementation boundary

V0.4 separates the trusted Django control plane (Admin, DB, approvals, queue) from
untrusted Django test execution. `AGENTFORGE_VERIFICATION_BACKEND="docker"` is
the DEFAULT, and the Worker invokes `docker run` with **only a disposable copy**
of target source. No Docker socket, secrets, home directories, original project
folder or production database are mounted into the verifier.

The trusted queue process still runs as a separate host process / dedicated
worker VM with Docker Engine access. NEVER mount `/var/run/docker.sock` into
the public Django Web container: controlling the Docker daemon is approximately
equivalent to host root privilege. Restrict Docker control to dedicated operators.

### Setup (one-time)

```bash
docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .
python examples/django_host/manage.py process_agentforge_queue --max-jobs 2 --include-verify
```

The Docker verifier image must already be installed locally. Verification
never downloads an image during task execution (`--pull never`). For a real
Django project, build a vetted custom verifier image with ALL test dependencies
preinstalled, run as uid 65534, and configure
`AGENTFORGE_DOCKER_VERIFY_IMAGE="your-verifier:immutable-version"`. Use digest
pinning and regularly scan base images in production. This template is a
development proof of the executor contract only.

`docker run` receives:
- `--network none`, `--read-only`, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, `--pids-limit 128`,
  `--memory 768m`, `--cpus 1.0`, `--user 65534:65534`,
  temporary `/tmp` and `/run` tmpfs mounts.
- exactly one disposable bind mount to `/workspace`, never the original
  project, and only fixed `python manage.py check/test` commands.
- no inherited LLM API keys, secret environment, Docker socket, public network,
  deployment credentials, privileged mode or host production databases.

Missing Docker daemon/image, malformed input, timeout, failed check, zero Django
business tests, or unavailable dependencies => BLOCKED/FAIL, never PASS.
An explicit **unsafe legacy local** verification switch exists only for
trusted development:
```python
AGENTFORGE_VERIFICATION_BACKEND = "local"
AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY = True
```
**Do not use this legacy mode for external code or production.**

### Autonomous coding safety

The original AgentForge V2.0 coding pipeline still launches verifier subprocesses
in its own process. A Docker *post*-verification alone cannot make that earlier
execution safe. Therefore V0.4 **blocks AUTONOMOUS by default**, even when a
human has authorized write scope, until a separate isolated coding executor
and constrained LLM broker are implemented.

An explicit legacy trusted-development fallback exists, requiring ALL of:
`AGENTFORGE_ENABLE_LEGACY_HOST_AUTONOMOUS=True`,
`AGENTFORGE_VERIFICATION_BACKEND="local"`,
`AGENTFORGE_ALLOW_UNSAFE_LOCAL_VERIFY=True`, plus the original human approval
and model policy gates. This mode is **not secure against untrusted code** and
is not production-ready.

### REAL DeepSeek 3-round gate

A workflow_dispatch-only `.github/workflows/agentforge-django-v04-live.yml`
calls DeepSeek three separate times with a fixed read-only policy fixture. Each
round is independently checked against deterministic policy invariants: an
unauthorized settings change must be BLOCKED and independent business tests
are necessary. All three must PASS or overall FAIL; 429/5xx/network/model
failures do not count as success. The job writes a machine-readable JSON report
and returns a nonzero exit code on failure.

Configure Github Actions secret `AGENTFORGE_LLM_API_KEY` and variables
`AGENTFORGE_LLM_BASE_URL`, `AGENTFORGE_LLM_MODEL`; manually dispatch the
workflow. Without credentials it returns BLOCKED. This costs API usage and
is NOT automatically started by source push.

**This is a read-only model-policy gate**, not V2.0 full autonomous coding 3/3,
not integration of a real customer's business transaction tests, and not
production readiness. Never label offline fake-model tests as real DeepSeek
acceptance. Paid live results must include the actual run link and 3/3 counts.

### Security scope and remaining work

Docker shares the host kernel and Docker control is highly privileged. This
implementation is defense-in-depth for trusted projects on a dedicated Linux
worker, not isolation for active adversarial code or multitenant production.
Do not run user-supplied projects without a separately locked-down VM/microVM,
strict image provenance, resource quotas, rate limits, read-only control DB
credentials where possible and review of data exfiltration channels (especially
stdout and test fixtures). Temporary worktree creation excludes common secret
names, but file naming conventions cannot guarantee all secret data is removed.

NEXT GATE: isolated AUTO-CODING executor, external LLM broker with strict
token/cost/time budgets, supported independent business harness and 3/3 actual
code-generation rounds. Until that gate, V0.4 is a development framework.

### Running the real-model gate while this feature branch is isolated

GitHub `workflow_dispatch` normally requires the workflow file to exist on
the repository's **default branch**. This V0.4 branch intentionally does NOT
merge into `main`, so the manual workflow may not appear or dispatch until
maintainers explicitly merge/publish that workflow.

For now, use the equivalent local command in an authorized secure CI/terminal,
with `AGENTFORGE_LLM_BASE_URL`, `AGENTFORGE_LLM_MODEL` and
`AGENTFORGE_LLM_API_KEY` set as protected environment variables (not in source):
```bash
python scripts/run_django_v04_live_acceptance.py --output artifacts/django-v04-live/summary.json
```
This is an opt-in paid REAL DeepSeek request: exactly 3 model calls when
each returns a valid structured response (API retries may generate additional
attempts). No credentials => BLOCKED. It must not be confused with full
V2.0 autonomous coding stability acceptance.


## V0.5 — isolated candidate coding, broker and 3/3 fixture acceptance

The V0.5 code path is additive. The previous autonomous V2.0 subprocess
executor remains disabled by default. The new path enters only after all
existing project switches, an immutable human approval matching the exact
request/configuration/HEAD, Docker backend and explicit permission to send
source files to the external LLM.

The trusted Worker controls three separate typed calls:
Planner → Executor → Reviewer. Models return JSON text only; never agent-chosen
shell commands, npm/pip installs or test commands. Hard-coded Python policy
rechecks every planned path and edit: existing .py files only; 1-3 files;
source <=16 kB/file; complete replacement <=24 kB/file; settings,
migrations, test_*, manage.py, symlinks and out-of-scope paths are prohibited.
Review APPROVE is advisory only. No PR or deployment is permitted.

The candidate is written only to a disposable local copy. The Validator calls
the independent V0.4 offline Docker test gate (fixed Django check/test);
no production DB is mounted. A candidate becomes PROPOSED only when the
Reviewer approved *and* Docker independently passed real business tests.
Only the patch and sanitized gate evidence remain in the Django job result.
A failed validation is FAIL and no candidate patch is exposed.

### LLM broker limits and explicit consent

Set the preexisting `AGENTFORGE_LLM_BASE_URL` to
`https://api.deepseek.com`, `AGENTFORGE_LLM_MODEL=deepseek-chat`, and
`AGENTFORGE_LLM_API_KEY` only in the dedicated trusted Worker.
`AGENTFORGE_V05_ENABLE_SOURCE_TRANSFER` is false by default.
The separate `AGENTFORGE_V05_ALLOWED_LLM_HOSTS` defaults to
`api.deepseek.com`. The broker caps requests to 3, max output
tokens to 2048 per request, size of prompts/responses and an overall
150-second deadline. SDK retries are disabled for V0.5; no infinite retry
loop and no API credentials passed to Docker containers.

**IMPORTANT:** Without provider usage data, this is a request/token output
budget, NOT a verified cost ceiling. Source code is transmitted only after
the operator explicitly permits it; do not enable for sensitive third-party
sources absent organizational authorization. Docker isolation is not a secure
multitenant adversarial container sandbox. Production use still needs dedicated
VM/microVM boundaries, credential separation, immutable image provenance and
strong audit storage.

### Independent three-cycle benchmark

```bash
docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .
python scripts/run_django_v05_smoke.py
```
CI runs the smoke with **ScriptedFakeAgent**, but REAL Docker for the corrected
Django business test; offline passes must be labeled `SYNTHETIC_AGENT_REAL_DOCKER`.
A broken baseline is separately asserted to fail before a candidate is
accepted. The original fixture remains unchanged.

To use paid real DeepSeek for the same tiny synthetic project, in a dedicated
trusted CI terminal run:
```bash
python scripts/run_django_v05_live_acceptance.py --confirm-paid-calls
```
Each of 3 fully fresh iterations makes 3 real planner/executor/reviewer
calls and independently verifies the result in Docker. Success requires
3/3 completed code candidates plus untouched originals. The script's JSON
only records redacted status, patch hashes, model-call counts and gate facts.
A failure cannot be reclassified as success; missing API key => BLOCKED.

The alternate `workflow_dispatch` CI is opt-in and is not available from
GitHub's branch UI unless its workflow is already present on the default branch.
We do not modify `main` in this development branch.

This test **does not prove** 3/3 reliability on real customer Django apps,
secure execution against hostile code, actual monetary spend, or suitability
for deployment. No model-generated output is merged or pushed automatically.


## V0.6 — bounded repair, telemetry, external-worker preflight

### Code delivery loop and deterministic ceiling

The new optional `v06_repair.produce_candidate_v06` is selected inside
`run_approved_v05` ONLY when `AGENTFORGE_V06_BOUNDED_REPAIR=True`.
All original V0.5 gates continue to apply: explicit human approved Git SHA,
unchanged requirement/configuration, project + global allowlists, approved
source transfer, and Docker validation only.

Its flow: Planner → Executor → Reviewer → Docker check/test.
On a real failed check/test, at most once, Fixer returns a restricted
full-file edit for an already planned Python path, followed by a NEW Reviewer
and NEW independent Docker check/test. Blocked or infrastructure failures do
not trigger repair. Reviewer rejection means BLOCKED, not PASS.

Per-task limits: **5 role calls**, **2 Docker validation rounds**, **1 repair**,
a 150s trusted model broker deadline, maximum 2048 model output tokens per API
request, and 90-second timeout per fixed Django check/test subprocess.
These ceilings are bounded operations, not an audited total USD budget.
Task timing including process cleanup/daemon failures is not an OS-enforced
hard deadline. Any missing required evidence returns blocked/failed.

The Fixer only gets sanitized status (PASS/FAIL, allowlisted short failure reason,
numeric return code) and the prior candidate diff. Target stdout/stderr and
secrets are NOT inserted in its prompt. Models cannot change tests,
settings, migrations or run unapproved commands. The original Git directory
is never modified by this additive pipeline. A successful outcome is a
candidate patch only; human promotion remains external.

### Distinct trusted Worker

`examples/django_host/config/v06_worker_settings.py` fails closed unless:
- operator sets `AGENTFORGE_V06_ENABLE_WORKER=I_ACCEPT_DEDICATED_WORKER`
  and `AGENTFORGE_WORKER_ROLE=trusted-dedicated`;
- an explicit source-root allowlist and a non-demo Django secret exist.

Use on a separate trusted host with the ability to invoke Docker; do not
mount a Docker socket into the public Django container or assume role
environment markers provide kernel-level isolation. A separate VM and
dedicated database credentials are deployment responsibilities, **not
included in this reference implementation**.
Read `deploy/v06/README.md` for the deployment boundary and the one-pass
queue command. The demo SQLite DB is not suitable for a shared remote
worker.

### Evidence and acceptance honesty

The Control Center now shows model call counts, Docker rounds, repair
attempts and per-round outcome. Authorized JSON evidence export includes
bounded numeric budget fields and no raw candidate code/stdout/stderr.

`python scripts/run_django_v06_smoke.py` runs THREE distinct synthetic
coding loops. Every loop starts with an actual failing Django fixture;
the scripted initial fix still fails in real Docker; a scripted Fixer then
corrects it; a fresh Reviewer and a second independent real Docker check
must PASS. The original source remains unchanged. Evidence MUST be named
`SYNTHETIC_AGENT_REAL_DOCKER_V06`, never real DeepSeek 3/3.

`python scripts/run_django_v06_live_acceptance.py --confirm-paid-calls`
is the separate opt-in paid real DeepSeek 3-cycle entrypoint. It requires
3/3 candidate deliveries with independent Docker evidence on the fixed
synthetic fixture. It does not claim production customer project reliability,
provable monetary limits or secure hostile-code isolation. The manual GitHub
workflow cannot necessarily dispatch until placed in the default branch,
which this implementation does NOT modify.
