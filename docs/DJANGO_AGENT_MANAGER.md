# AgentForge Django Agent Manager V1.1

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


## V0.7 — ephemeral cross-process staging and broker regression

V0.6 critical contract repair: `create_v05_broker(max_requests=5)` used to
raise TypeError even though mocked CI broker calls passed. The function now
accepts ONLY the bounded 3/5 budgets. In addition, it rejects HTTP, non-443
ports, userinfo, fragments, query tokens and non-allowlisted DeepSeek hosts.
Never use a potentially forwarded Authorization bearer over plain HTTP.

Staging CI now starts actual ephemeral PostgreSQL and a Django web subprocess,
creates an operator-approved autonomous synthetic job (with immutable Git
commit and scope), then launches a separate worker Python process. The worker
uses a ScriptedFakeModel and real Docker check/test across a failing first
candidate and a repaired passing second candidate. Both control and worker
persist state via PostgreSQL; the source repository stays unmodified.
CI report key: `EPHEMERAL_POSTGRES_CROSS_PROCESS_REAL_DOCKER_FAKE_LLM`.

THIS IS NOT A PERSISTENT VM DEPLOYMENT. GitHub CI web/worker processes share a
runner host OS and Docker daemon. It cannot establish hostile-code isolation.
No public endpoint is exposed; runserver listens on 127.0.0.1 only.
Its explicit synthetic-only gate prevents accidental use as a real worker.

The paid 3-round DeepSeek acceptance remains separate and is not run by default.
Never treat fake-agent staging pass as real-model 3/3 reliability. See
`deploy/v07/README.md` for service deployment and approval prerequisites.


### V0.7 persistent deployment safety correction

`config.v07_worker_settings` now requires a verified-TLS PostgreSQL
connection, dedicated-VM confirmation, and inherited V0.6 worker gates.
`config.v07_control_settings` requires the same externally hosted DB
and has LLM source-transfer/worker flags forcibly OFF, and requires HTTPS
session/CSRF cookies. The `deploy/v07/agentforge-worker.service` template
points to `v07_worker_settings`, not demo SQLite. Missing remote TLS CA,
DB secrets, role marker or permission roots causes settings import to fail.

The code is deployable configuration, NOT a claim that a remote VM,
PostgreSQL service or live DeepSeek integration has already been provisioned.


## V0.8 — candidate patch handoff and lease observation

V0.8 adds a read-only superuser-only `GET /agentforge/jobs/<uuid>/candidate.patch`
endpoint. It downloads a **candidate** patch, never applies, merges, publishes
or modifies Git. Before returning bytes the server checks:

- task mode AUTONOMOUS, final status PROPOSED, unbroken audit hash chain;
- exact SHA-256 matches patch content and maximum 100 KB size;
- original approver is still an active staff superuser;
- original request and project configuration still match the human approval;
- scope unchanged, source file manifest 1–3 existing .py paths within approved scope;
- every patch header matches that original manifest;
- two passing offline Docker check/test results with positive business test evidence;
- result explicitly denies production release.

Failure is 403. This is a protected source-code export for human review, not
permission to run `git apply` automatically. Treat downloaded source as
confidential. Immutable commit anchoring and patch review remain human tasks.

Use `python examples/django_host/manage.py inspect_agentforge_leases --json`
to inspect live/stale-looking project locks. The suspected-stale flag is based
on **elapsed time only**, cannot prove a worker died, and never releases a
lock or retries a task. The existing explicit operator recovery remains the
only release path after an interrupted job.

V0.8 also suppresses a late stale Worker's final_gate event after manual
operator recovery. That worker's result is never resurrected. Do not run
a recovery command while a Worker is still alive; process termination must
be verified out-of-band.

### Acceptance remains separate

Django Python 3.11/3.12 unit tests and real Docker CI establish integration
correctness. The real DeepSeek 3/3 gated workflow remains OFF unless the
owner explicitly configures protected credentials and fee approval. No
persistent external VM has been provisioned by this patch.


## V0.9 — durable PostgreSQL worker heartbeat and bounded supervisor

V0.9 adds `JobLease.heartbeat_at` via migration 0004, and a dedicated
PostgreSQL heartbeat thread for **trusted Worker processes only**.
The remote worker settings turn it on (10s interval), while the
temporary GitHub CI worker uses a 1-second interval and verifies the
heartbeat independently alongside real Docker tests.

The heartbeat updates only the row matching the exact job and immutable
owner token. If the row disappears or its status ceases to be RUNNING,
the heartbeat is marked lost and finalization fails closed: no PASS or
PROPOSED status is permitted. PostgreSQL error or stopped heartbeat
also blocks finalization. Legacy SQLite demo remains heartbeat OFF;
attempting to enable heartbeat in SQLite is rejected before claiming a job.

`inspect_agentforge_leases --json` now reports `heartbeat_age_seconds`
and liveness `RECENT_HEARTBEAT`, `HEARTBEAT_OVERDUE_CHECK_PROCESS`, or
`UNKNOWN_LEGACY_NO_HEARTBEAT`, alongside lock age. Heartbeat staleness
is NOT proof a process died. No automatic lease stealing or retry exists.

For a dedicated Linux VM, an optional bounded **one-job** supervisor is
available:

```bash
python examples/django_host/manage.py supervise_agentforge_job <UUID> --timeout-seconds 900
```

It requires `AGENTFORGE_WORKER_ROLE=trusted-dedicated`, dedicated worker
settings, and PostgreSQL heartbeat enabled. It starts a child process and
terminates its Unix process group after timeout. The supervisor does NOT
reclaim the lease, retry, or assert Docker containers have terminated:
the Docker daemon may continue a container after its CLI exits. A human
operator must verify process/container state before using the existing
explicit `recover_agentforge_job` operation.

This is a reliability and fencing improvement, NOT a claim of hostile-code
microVM sandboxing or persistent VM deployment. The source/DeepSeek data
transfer permissions remain OFF unless explicitly authorized.


## AgentForge V1.0 — atomic Worker fencing and real-model failure attribution

**Candidate success and audit finalization are now one atomic database operation.**
Both the Worker and manual recovery lock `AgentJob` and then `JobLease`
in the same order. The Worker must still hold the *exact* owner token before
committing any final PASS/PROPOSED, and every worker audit event is also
fenced to a RUNNING job with its original lease. A recovered job's final
`operator_recovery` event cannot be followed by a late Worker success event.

If the ownership lease disappeared, V1.0 **leaves the job for operator
investigation**, never fabricates a success or takes ownership from another
Worker. Expired heartbeat or a heartbeat DB fault blocks candidate delivery.
The migration/heartbeat features from V0.9 remain unchanged.

V1.0 also adds read-only model readiness inventory and a typed, redacted
result classifier, used by the *opt-in* DeepSeek 3-round script:

```bash
python scripts/check_agentforge_v10_readiness.py \
    --output artifacts/agentforge-v10-readiness.json
```

The inventory **never calls DeepSeek or Docker**, and always reports
`real_deepseek_three_round_result: NOT_RUN`. It merely checks whether
necessary local settings/CLI are present; secret values are never printed.
Real DeepSeek API calls require the already-existing explicit paid-run gate,
and remain **NOT RUN** unless the user enables it. A true result report
distinguishes MODEL_TRANSPORT_OR_SCHEMA, POLICY_OR_PRECONDITION,
MODEL_REVIEW_REJECTED, INDEPENDENT_BEHAVIORAL_TEST_FAILED, and
VERIFICATION_INFRASTRUCTURE. It never serializes raw model prompts,
stdout/stderr or exception strings.

New CI tests cover the following *negative* cases: old Worker tries to
finalize after operator recovery, foreign owner token, missing lease,
heartbeat loss/expiry, and model/API error messages containing secrets.
PostgreSQL integration CI continues to check the actual cross-process
Worker + Docker candidate-only loop, and core regression checks stay on.

**Honest V1.0 boundary:** engineering CI passing is not real DeepSeek
3/3 coding stability, not a dedicated external VM deployment, not a
security-certified adversarial sandbox, and not production release permission.
No `main` merge or paid model call is automatic.


## V1.1 — 三类 Django 真实 Docker 基准与受控 DeepSeek 验收

V1.0 已经完成了 Worker/审计权限加固。V1.1 的重点是**扩大真实业务验收覆盖度**，
而不是把同一个 `add(a,b)` 简单算术题重复三次。

新增固定合成基准（全部为新建的测试项目，不使用用户业务代码）：
1. `arith-001`：正数、负数和零的计算；
2. `pricing-002`：折扣金额、100%/0% 边界、整数舍入；
3. `access-003`：对象拥有者、员工访问、未授权用户和匿名身份保护。

三套原始程序必须各自先在 **真实离线 Docker** 中出现业务测试失败；
之后每套由独立模型 Planner/Executor/Reviewer 或 Fixer 生成修复候选，
重新进入独立 Docker 检查。只有至少分别通过 3、4、5 条真实业务测试，
源代码与测试原件完全未改动、模型角色调用不超过每例 5 次，
结果才是 `PASS`。每例都报告源代码/测试摘要及候选补丁哈希。

在 GitHub Actions 或有 Docker 的环境先执行免费验收：

```bash
docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .
python scripts/run_django_v11_offline.py
```

此命令仍使用 `SCRIPTED_FAKE_AGENT`，但 Django Docker 检查和业务测试
是真实执行的；即使全部通过也不能把 `real_model_verified` 标记为真。

明确同意 API 收费后，才允许配置真实 DeepSeek 环境变量并手工运行：

```bash
python scripts/run_django_v11_live.py --confirm-paid-calls \
    --output artifacts/django-v11-live/report.json
```

三个不同案例需要 3–5 次角色 API 请求/例，最多 15 次逻辑请求。
要求 `AGENTFORGE_LLM_API_KEY`、`AGENTFORGE_LLM_BASE_URL=https://api.deepseek.com`
和 `AGENTFORGE_LLM_MODEL=deepseek-chat`，以及预构建的 Docker 验证镜像。
付费的工作流 `agentforge-django-v11-live.yml` 额外受到 GitHub Repo 变量
`AGENTFORGE_V07_PAID_LIVE=I_APPROVE_THREE_DEEPSEEK_RUNS` 门禁保护。
默认 push 不触发付费任务。工作流通常需要位于 GitHub 默认分支才可直接
使用 workflow_dispatch；本次不改动 main。

验收分为 `模型/网络问题`、`Reviewer 拒绝`、`业务回归失败`、
`验证环境问题`、`初始缺陷未复现` 等。
输出仅包含脱敏的分数、计数、哈希和错误类别，不包含源代码、
提示词、API 密钥及测试原始日志。**3/3 合成基准通过不等于实际业务项目已
达到生产可用性，也不证明多租户恶意代码隔离。**


## V1.1 真实 DeepSeek 接口验收加强

本阶段增加**真实 HTTP 请求格式的离线契约测试**，检查 DeepSeek 请求地址、
Authorization、模型、`max_tokens`、请求失败扣额度和 429 不重试。
同时记录 API 返回的 `usage.prompt_tokens`、`completion_tokens`、
`total_tokens`，仅在提供方返回完整、合法数据时计数；
**没有 usage 字段绝不能声称 token 费用已测量**。

现有真实 DeepSeek 3/3 付费工作流仍然为显式 opt-in，
未启用时不会调用 API。HTTP 模拟测试不等于真实 DeepSeek 已通过。
生产 VM 与真实业务项目验收也仍独立。


## V1.2 — 真实模型三案例验收数据与人工对比报告

本阶段保留 V1.1 的三个真实 Django 基准：算术、整数折扣和对象权限，
不继续靠重复同一道题提升数字。每例都追踪 Planner、Executor、
Reviewer、Fixer 的调用结果，并记录角色请求数、经过一次修复的案例数、
Docker 业务测试的实际用例数。模型提示词、测试原始日志和 API
密钥绝不进入可公开的报告。

来自 DeepSeek API 的 token 字段只在服务器真正返回有效 usage 时汇总。
覆盖情况独立标为 COMPLETE、PARTIAL 或 UNKNOWN。部分失败请求
可能不会返回 token 统计，所以使用量不是完整费用凭证，
也不推断人民币或美元总费用。离线 ScriptedFakeAgent 的覆盖状态固定
为 NOT_APPLICABLE，绝不能声称真实模型通过。

免费验证：
~~~bash
python scripts/run_django_v11_offline.py
python scripts/render_django_v12_report.py \
  --input artifacts/django-v11/offline-report.json \
  --output artifacts/django-v11/operator-summary.md
~~~
Docker Smoke CI 使用真实 Docker 业务测试与脚本模拟 Agent，
输出 JSON 与 Markdown 两份证据。同一个验收逻辑被真实 DeepSeek
入口复用，真实运行时可执行：
~~~bash
python scripts/run_django_v11_live.py --confirm-paid-calls
python scripts/render_django_v12_report.py \
  --input artifacts/django-v11-live/report.json \
  --output artifacts/django-v11-live/operator-summary.md
~~~
第二段是**付费**模型调用入口，不会因为正常 git push 自动执行。
仓库原有 GitHub Actions 付费工作流仍有明确变量门禁。本次没有修改该
付费工作流，也没有触发它；任何实际模型验收结论必须同时检查对应
GitHub 运行日志及原始脱敏 JSON 证据。

V1.2 的 CI 通过只证明报告正确生成和现有工程回归稳定，
不证明真实 DeepSeek 3/3、持久化独立 VM 已部署或生产可用。


## V1.3 · 真实 DeepSeek 运行可信来源与可恢复证据

本阶段修正验收漏洞：不能只传入 `model_kind=REAL_DEEPSEEK`
就把脚本模拟 Agent 的成绩标记为真实模型成功。三案例实际运行器在
**调用模型之前**验证客户端必须是受限 `BoundedDeepSeek`
类型，并检查正式 HTTPS DeepSeek 接口、`deepseek-chat`、
禁重试设置、尚未消费的五次请求限额及密钥非空。
未通过校验时案例直接失败，整套报告 `real_model_verified=False`。

真实模式还会在第一笔模型 API 请求之前，先使用 Docker
**完整检查全部三个不同基准的原始缺陷**。其中任何一个不具备
合格的失败基线，直接停止且不产生付费调用。
这些检查只证明当前合成基准可执行，不是生产环境安全证明。

付费任务现在每完成一个案例就写入独立的
`checkpoint.json`，使用同目录临时文件和原子替换，
只包含固定白名单的案例编号、结果、错误类别和请求计数。
检查点明确标记 `INCOMPLETE_UNTIL_FINAL_REPORT`、
`real_model_verified=False`；流程中途崩溃不会把部分结果冒充 3/3。
最终报告仍是 `report.json`，不会包含原始源码、提示词或异常内容。
GitHub Actions 额外保留 Markdown 人工审查摘要。

真实付费工作流 `.github/workflows/agentforge-django-v11-live.yml`
已改为**仅可手动触发**，不再因修改这个文件而触发付费工作；
同时仍需要仓库管理员显式打开
`AGENTFORGE_V07_PAID_LIVE=I_APPROVE_THREE_DEEPSEEK_RUNS`
并提供 `AGENTFORGE_LLM_API_KEY`。在 GitHub UI 中，该工作流
通常需要先存在于默认分支才能使用 workflow_dispatch；
本阶段**不修改 main、不自动配置密钥、不授权付费**。

重要：运行时客户端类型检查只是防止误用的工程控制，
不是可独立验证的远程模型身份/消费证明。只有对应的 GitHub
执行日志和服务商账单/用量信息，才能进一步佐证实际 API 调用。
即使真实三案例 3/3，也不能据此认定已通过任意生产项目或恶意代码隔离测试。


## V1.4 — 独立验收证据一致性检查

本阶段先修复 V1.3 GitHub CI 的旧断言：
`tests/test_v11_cli.py` 过去错误地要求付费 workflow 必须包含
`paths:`。V1.3 已主动移除 push 触发，所以该测试现在明确要求
**只能 workflow_dispatch 且绝不包含 push 触发**。这保持了更安全的
“默认不产生费用”控制，不做回退。

新增：
- `src/agentforge_django/v14_evidence.py`：复核 3 个基准场景顺序、
  固定 manifest 指纹、源文件和测试文件的 SHA-256、实际测试数、
  模型角色请求数、单例/总体 PASS 一致性、token 来源标记和
  部署权限默认关闭；
- `scripts/verify_django_v14_evidence.py`：只读本地 JSON，
  不联网、不启动 Docker、不调用付费模型；输出原子写入且
  默认权限 0600 的 `v14-evidence-receipt.json`；
- `django_tests/test_v14_evidence.py`：包含伪造模型标签、
  篡改测试数、修改原测试文件指纹、虚报调用次数和
  伪造生产发布授权等拒绝用例。

运行命令（先要有 V1.2 的实际 JSON 报告）：
~~~bash
python scripts/verify_django_v14_evidence.py \
  --input artifacts/django-v11/offline-report.json \
  --output artifacts/django-v11/v14-evidence-receipt.json \
  --expected-model SCRIPTED_FAKE_AGENT --require-pass
~~~

真实 DeepSeek 手动工作流亦加入同一校验器，输出额外回执；付费
三案例运行依旧需要管理员明确配置密钥及授权变量才能触发，
本次**没有进行任何付费模型调用**。

**验收边界：** 这是“同一仓库中生成的报告和预置基准是否自洽”的
校验，不是第三方签名，不是服务商身份或 API 消费的独立证明。
操作者若能同时改写报告和校验器，SHA-256 不能阻止其伪造。
验证真实 DeepSeek 使用情况仍需对照对应 GitHub Actions
运行记录、API 服务商用量账单及可信执行环境。也不是已完成
持久 VM 生产部署或对抗性沙箱安全认证。



## V1.5 — 模型角色顺序和 Token 证据强一致性

V1.4 的验收回执已经具备固定基准 manifest、源码/测试哈希、
Docker 正向业务测试数和总体报告防篡改校验。V1.5 进一步校验：

- PASS 必须完整对应 `Planner → Executor → Reviewer`，或者仅一次
  修复时对应 `Planner → Executor → Reviewer → Fixer → Reviewer`；
  同时强制每个角色的 schema 接受状态为成功；
- 模型角色请求数、允许的修复次数和独立 Docker 验证轮数必须一致；
  任意删除 Reviewer、虚增调用次数、伪造二次验证都将拒绝 PASS；
- 来自真实 DeepSeek 的使用量必须满足 coverage、
  `provider_usage_reports`、逐案例 token 和总 token 的一致性；
  未报告的模型费用继续保留 UNKNOWN，不能自动被认作 $0；
- 全套角色计数、单次修复成功案例、缺失调用数必须与案例级记录一致。

新增 `django_tests/test_v15_consistency.py`，覆盖伪造角色轨迹、修复数、
Docker 验证数、token 覆盖率及合法无修复/一次修复路径。

验收仍然仅检查报告内部的逻辑一致性，不能证明模型供应商身份、
防止同一操作者同时伪造报告和校验程序，也不意味着独立云 VM 已部署。
真实 DeepSeek 三案例仍未在本阶段运行，原有手动付费门禁不变。


## V1.6 — Docker 测试防篡改写入屏障

本阶段修复独立验证器的真实安全隐患：此前容器虽然指定
`--read-only`，但项目代码挂载 `--mount type=bind` 默认仍可写。
恶意候选代码可能在 `manage.py check` 阶段修改临时业务测试文件，
继而影响 `manage.py test` 的真实通过结果。

修复方式：
1. Docker 项目挂载现在显式使用 `dst=/workspace,readonly`，
   禁止容器内对任何项目文件的新增、删除、覆盖；
2. 拷贝后的目录/文件权限从 `0777/0666` 收紧为 `0755/0644`，
   不再给非特权测试用户额外写权限；
3. 对临时工作区完整文件清单、路径和字节内容计算 SHA-256 指纹，
   每条 Docker 检查执行前后校验；发生任何文件篡改，
   立即设置 `VERIFICATION_WORKTREE_MUTATED`，不执行后续测试；
4. 增加真实 Docker 攻击测试：候选代码在 `check` 阶段尝试覆写
   `app/tests.py`，必须失败；合法修复仍必须成功通过 Django
   正向业务测试。原始项目不会被修改。

测试：
~~~bash
docker build -t agentforge-django-verify:0.4 -f docker/Dockerfile.verify .
python scripts/run_django_v16_write_barrier_smoke.py
~~~

安全边界：只读挂载是防止验证阶段改写测试的保护，
**不是**恶意代码不可突破的内核级隔离；Docker daemon 或宿主被控制、
测试本身有逻辑漏洞、模型假造行为等问题仍需要更强独立 VM/
微虚拟机、可信镜像摘要、审计与人工审批。实际 DeepSeek 付费调用
及持久 VM 部署仍未执行，本阶段不将测试脚本称为真实模型验收。


## V1.7 — 防止 Docker 验证镜像标签被替换

`docker_verification` 现在先使用本地 Docker Engine 查询
`image inspect --format '{{.Id}}'` 获取 **sha256:64 位**镜像配置 ID，
验证格式后使用该 ID（而不是可变的 `agentforge-django-verify:0.4`
标签）执行后续 `check` 和 `test`。两轮任务复用同一个镜像 ID；
检查到不存在、格式异常、与预先批准 ID 不一致均拒绝运行，不自动
pull、build 或执行本地宿主测试。

**持久 Worker 配置** `config.v07_worker_settings` 现在
强制要求 `AGENTFORGE_DOCKER_VERIFY_IMAGE_ID=sha256:...`；
在专用 VM 上先审核构建来源/镜像内容，再执行：

~~~bash
docker image inspect --format '{{.Id}}' agentforge-django-verify:0.4
~~~

将返回的完整镜像 ID 作为 Worker 的受保护环境变量。服务启动后，
标签被指向另一个镜像时会直接阻断。设置只能由 VM 操作员维护；
不用客户项目源码或 LLM 输出来设置 pin。

新增 `scripts/run_django_v17_image_identity_smoke.py` 在真实 Docker
上验证正确 pin 可通过、错误 pin 必须被阻止，并核对返回证据与
实际镜像 ID 一致。附加离线测试模拟镜像标签变化及无效 Docker
响应，确认验证脚本不能绕过 ID 检查。

**边界：** Docker 镜像 `.Id` 是本地 image config/content ID，
**不是** registry manifest digest、签名校验、SBOM 或 Docker daemon
可信性证明。本阶段未部署独立持久 VM，亦未触发真实 DeepSeek 付费请求。


## V1.8 — 专用 Worker 启动预检（不调用付费 API）

新增 `python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json`。

预检 **只读** 检查：独立 Worker 角色和显式部署许可、关闭旧版宿主执行功能、
可信项目根目录、远程 PostgreSQL 的 TLS `verify-full` 配置、
**实际 PostgreSQL SELECT 1**、AgentForge Django migrations 全部已安装、
已开启数据库心跳、已审批 Docker 镜像 SHA-256 ID 与本机镜像一致、
以及 Worker 的 DeepSeek 密钥仅在受信任进程存在。输出
`ready_to_accept_candidate_only_jobs` 和固定错误码，不打印密钥、模型提示词、
数据库密码或用户项目源码。

服务模板 `deploy/v07/agentforge-worker.service` 已加 `ExecStartPre`：
检查失败就阻止 Worker 接单，不执行迁移、不自动拉镜像、不修改 Git。
可在专用 Linux VM 上使用以下命令验收（需事先配置已批准的环境文件）：

~~~bash
DJANGO_SETTINGS_MODULE=config.v07_worker_settings \
python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json
~~~

GitHub CI 则在**临时同主机环境**使用 `--mode ci-staging`，它只接受
`CI=true`、隔离的测试 PostgreSQL localhost 和无 DeepSeek Key；
在真正执行合成任务之前，单独启动 Django Worker 预检进程并验证
全部检查成功。缺数据库、迁移、镜像身份或权限时会先拒绝接单。

**没有**因通过 CI 而宣称独立持久 VM 已部署、外部 PostgreSQL 已 provision，
也没有真实 DeepSeek 三案例付费运行。此命令验证的是准备条件，
不能证明 Docker 守护进程未被入侵或 VM 物理独立，也不自动开启生产发布权限。
