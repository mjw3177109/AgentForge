# V0.7 Worker — deployment boundary

This folder provides deployment templates and an ephemeral CI smoke test.
It does **not** provision or deploy any VM, production PostgreSQL, cloud
project, persistent queue daemon or real DeepSeek request.

## What really runs in GitHub CI

The v07 staging workflow starts PostgreSQL 16 as an Actions service,
a Django HTTP subprocess with control-only settings, and a separate
trusted Worker subprocess using the same test DB. An approved synthetic
task exercises Planner, Executor, Reviewer, one Fixer, second Reviewer
and two REAL offline Docker Django check/test rounds. The model is
`FakeRepairModel` and no LLM API key is used. No user project is read.
CI ends by destroying the temporary worktree and DB.

This proves cross-process Django/PostgreSQL handoff and the original
source remaining untouched. All processes still live on the SAME
GitHub runner host: this does not prove VM/hostile-code isolation.

## Actual persistent Worker — not deployed by this task

On an explicitly provided trusted VM (not the web app machine):

1. Provision a dedicated Linux VM, Docker daemon restricted to VM, a
   private database reachable over verified TLS, and read-only access
   to allowlisted trusted Django repositories. Create a dedicated
   `agentforge` OS account and protect the workers' source tree.
2. Install `python -m pip install -e ".[django,staging]"` and vet a
   pinned Docker verifier image with target app dependencies installed.
3. Configure Django DATABASES for the remote PostgreSQL database.
   **Do not use CI-only v07_staging settings**: these refuse remote
   database hosts and require `CI=true`.
4. Keep API tokens only in the trusted Worker secret manager, never
   in the public Django web app, Git repository or Docker validator.
5. Install a protected root-owned environment file in
   `/etc/agentforge/v07-worker.env` (mode 0600), or preferably use
   systemd credentials/secret management. Do not commit it.
6. Run an explicit one-shot worker on a private host:
   ```bash
   DJANGO_SETTINGS_MODULE=config.v06_worker_settings \
   python examples/django_host/manage.py process_agentforge_queue \
       --max-jobs 1 --include-autonomous
   ```
   V0.6 settings require explicit role, strong Django key and
   allowlisted roots. Your production settings must also replace
   demo SQLite and configure production-safe PostgreSQL TLS.
7. Only after OS/microVM isolation and network policy reviews should
   the operator install the optional systemd unit/timer in this folder.
   It is disabled unless an operator actively enables it.

Do not mount Docker daemon socket into public web. A Docker-capable
Worker is powerful on its VM. Generic Docker is not malicious
multi-tenant isolation; no production-readiness assertion is made.

To run REAL DeepSeek 3-round synthetic-fixture tests, use the manual
paid-acceptance script only with an expressly approved API key; success
on that fixture does NOT prove a real customer's Django project.
