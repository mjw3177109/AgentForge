# AgentForge V1.9 — manual recovery runbook

No persistent VM is provisioned by this repository. Execute all commands on
the trusted Worker VM, never in a public web container.

**Startup**: verify protected PostgreSQL/CA settings, model-key isolation and
operator-approved Docker image; use
`manage.py check_agentforge_worker --mode dedicated --json` and require
all **12/12** checks. The check includes an empty Docker orphan inventory.

**After an unexpected crash, timeout, or reboot:**

1. Stop `agentforge-worker.timer` and `agentforge-worker.service`.
2. Inspect OS processes and confirm the OLD worker and children truly stopped.
   An expired database heartbeat is not proof of process termination.
3. Run `manage.py inspect_agentforge_leases --json` and
   `manage.py inspect_agentforge_containers --json --fail-if-any`.
   Independently inspect `docker ps -a --filter
   label=org.agentforge.verifier=django-offline`.
4. Only after identifying an obsolete *exact* generated container name may
   the operator manually remove that container with
   `docker rm -f -- <exact-container-name>`; do not blind-prune.
5. Rerun the orphan inventory. It must be empty. Verify no remaining worker
   process or detached Docker process belongs to the interrupted job.
6. THEN run `manage.py recover_agentforge_job <job_uuid>
   --confirm-worker-stopped`. The interrupted job is BLOCKED, never
   automatically resumed or deployed.
7. Run the dedicated preflight again before re-enabling the timer.

The service config sets `KillMode=control-group`, `TimeoutStopSec=30`,
`SendSIGKILL=yes`, and `Restart=no` but systemd process groups cannot
guarantee that a Docker daemon container has exited.

Docker daemon access confers strong host privileges; image config SHA IDs are
not signatures. This workflow does not certify malicious-code isolation.
