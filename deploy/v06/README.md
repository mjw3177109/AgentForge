# V0.6 dedicated worker — staging example, not production deployment

**Use a dedicated trusted VM or physically separated Docker-enabled host.**
Do not run this as the public Django web process. The Django operator/web
process must NOT possess a Docker socket or LLM API token.

1. Provision a host with Python 3.11+, Git and Docker, and an existing trusted
   image `agentforge-django-verify:0.4`. This reference image contains Django
   only; for real projects create pre-vetted images with pinned dependencies.
2. Give the worker **read-only** access to allowlisted project source. Keep
   production DB credentials and production cloud credentials completely absent.
3. Use a database accessible to both the control plane and worker **with
   appropriate separation and minimum DB privileges**. The provided
   `examples/django_host/config/settings.py` uses local SQLite for demos
   only and CANNOT act as a shared cross-VM production database.
4. Set a strong `DJANGO_SECRET_KEY`, `AGENTFORGE_ALLOWED_ROOTS` and credentials
   via the VM's secret manager, not a committed environment file.
5. Explicitly enable V0.6 only in the worker context:
   ```bash
   export DJANGO_SETTINGS_MODULE=config.v06_worker_settings
   export AGENTFORGE_WORKER_ROLE=trusted-dedicated
   export AGENTFORGE_V06_ENABLE_WORKER=I_ACCEPT_DEDICATED_WORKER
   # Set the remaining vars out of band, using your secret manager.
   python examples/django_host/manage.py check
   python examples/django_host/manage.py process_agentforge_queue --max-jobs 1 --include-autonomous
   ```
   This is a one-pass queue worker, NOT a background daemon. Trigger it from
   an OS scheduler/supervisor on the dedicated host, not from HTTP.
6. Only tasks with matching immutable human approvals and explicit scoped source
   transfer can be executed. Result is PROPOSED candidate code, never deployed.

**Important unresolved risks:** Docker is not VM isolation; Docker daemon
access confers host-level power; source code copied to model provider is an
external data disclosure; file-based secrets are not guaranteed to be removed
by filename filtering; Django tests can interact with local container
filesystem. Treat this as a staging proof, not a secure multi-tenant service.

Boundaries: 5 attempted model role calls, 2 Docker check/test rounds, 1 repair,
90 seconds per Docker check/test subprocess, 2048 output tokens/LLM request.
No total currency budget claim and no guarantee of process-wide hard timeout
for Docker daemon failures. Operator must manually recover crashed worker lease.
