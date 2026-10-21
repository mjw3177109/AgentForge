# AgentForge V2.4 — stage-only, real-host systemd verification

This is a handoff package for a **separately provisioned dedicated Linux VM**.
No VM, paid DeepSeek account or remote PostgreSQL is provisioned by this
repository. NEVER stage the Docker-capable Worker on the public web host.

## Prerequisites (operator must verify)
- Source tree at /opt/agentforge/AgentForge, reviewed commit SHA.
- Private venv at /opt/agentforge/venv/bin/python; agentforge Unix user.
- Root-owned /etc/agentforge/v07-worker.env with protected permissions;
  no secrets in the Git repository or CI artifacts.
- Approved Docker image SHA256 ID, separately restricted Docker daemon.
- Remote PostgreSQL with authenticated TLS verify-full, trusted CA and
  migrations already completed under a separate explicitly approved operation.
- The trusted Worker preflight is required to pass 13/13 before any job.

## Staging — will NOT start or enable the timer

```bash
python3 scripts/check_django_v23_systemd.py
sudo bash deploy/v24/stage_units.sh --stage-reviewed-units
python3 scripts/audit_django_v24_systemd_host.py \
  --output /tmp/agentforge-v24-installed-units-audit.json
systemctl cat agentforge-worker.service
systemctl cat agentforge-worker.timer
```

The staging script refuses installed/existing unit files or overrides rather
than overwriting them. It validates the reviewed source unit files, installs
fresh copies under /etc/systemd/system, and calls daemon-reload only.
If a partial installation remains after a failure, investigate manually.

The read-only audit checks exactly which unit files systemd currently exposes,
that no drop-in override is present, NeedDaemonReload=no, service inactive and
timer disabled. It never reads secret environment-file contents, starts a
service, enables a timer, modifies a DB or calls the model. Failures generate
fixed codes without raw systemctl messages.

A passing V2.4 audit is **not** permission to turn on autonomous execution.
Review all preflight gates and cloud/security costs in an independently
approved manual activation step. The same-worker CI tests do not demonstrate
a deployed persistent VM or a live DeepSeek 3/3 acceptance.
