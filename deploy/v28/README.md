# AgentForge Django V2.8 — independent Worker host acceptance receipt

**Status: release blocked until a real dedicated Linux VM is independently
reviewed.** This is a read-only verification handoff, not a deployment.
It never activates the Worker timer, claims a task, applies migrations, runs
Docker builds, or calls DeepSeek. Running tests in GitHub Actions does not
provide a real VM acceptance result.

## What changed

`scripts/verify_django_v28_host_acceptance.py` requires ALL six gates:

1. Locally deployed Git HEAD matches the full 40-character SHA supplied by
   the operator from an independent trusted source.
2. Worker source/deploy tree has a clean Git worktree.
3. V2.5 host account, interpreter and root-owned secret-file metadata pass.
4. V2.7 full source/deploy tree metadata pass.
5. V2.4 **actual installed** systemd service/timer pass, inactive and disabled.
6. A fresh (no more than five minutes old), root-owned `0600`, 13/13,
   **dedicated** Worker JSON preflight receipt passes all named checks.

The Worker preflight itself performs a PostgreSQL `SELECT 1`, checks
`verify-full` PostgreSQL transport configuration and migration state, detects
stale job leases, validates the Docker verifier pin and absence of orphan
containers. V2.8 verifies its output; it does not replay the database check.

Receipts use only fixed verification keys, failure codes, count fields and SHA
fingerprints. They exclude paths, usernames, provider credentials and raw
command output. **The receipt is evidence for manual review, not a
cryptographic VM attestation or approval to enable the Worker.** A privileged
operator could forge a JSON receipt; secure VM access and change control are
still mandatory.

## 1. Operator-approved VM preparation (not automated)

Use a persistent, dedicated Linux Worker VM, NOT the public Django web host.
First verify the reviewed release commit independently and provision the
approved restricted Docker daemon and trusted PostgreSQL TLS CA. DB migrations
must already have been reviewed and executed separately. Protect
`/opt/agentforge/AgentForge`, `/opt/agentforge/venv`, and the
`/etc/agentforge/v07-worker.env` file according to the V2.5/V2.7 runbooks.

For a brand-new staging VM only, install **disabled** systemd units using the
existing V2.4 tool, after independent review:

```bash
cd /opt/agentforge/AgentForge
python3 scripts/check_django_v23_systemd.py
python3 scripts/check_django_v25_host.py
python3 scripts/check_django_v27_source_tree.py
sudo bash deploy/v24/stage_units.sh --stage-reviewed-units
python3 scripts/audit_django_v24_systemd_host.py
```

DO NOT run the staging installer against existing, previously activated or
production Worker units. V2.4 intentionally rejects those configurations.

## 2. Generate a fresh read-only Worker preflight receipt

This requires an **explicit human action on the actual VM**. Because the
Worker EnvironmentFile is root-owned `0600`, the preflight must be launched
under a service-equivalent systemd context: PID 1 reads the secrets and the
process runs as the unprivileged `agentforge` user. The preflight command
reads configuration, DB, migration status and Docker identity; it does **not**
claim a task or invoke DeepSeek. It *does* contact the remote PostgreSQL DB
with the approved read-only queries.

The following is a **preflight-only transient unit**, not the worker service
or timer. Review it on your VM and execute only when authorized to test
network access to remote PostgreSQL:

```bash
sudo install -d -o root -g root -m 0700 /var/lib/agentforge/v28
sudo sh -c '
  umask 077
  systemd-run --quiet --wait --pipe --collect \
    -p User=agentforge \
    -p Group=agentforge \
    -p WorkingDirectory=/opt/agentforge/AgentForge \
    -p Environment=DJANGO_SETTINGS_MODULE=config.v07_worker_settings \
    -p EnvironmentFile=/etc/agentforge/v07-worker.env \
    -p NoNewPrivileges=true \
    -p PrivateDevices=true \
    -p ProtectSystem=full \
    -p ProtectHome=true \
    -- /opt/agentforge/venv/bin/python \
    /opt/agentforge/AgentForge/examples/django_host/manage.py \
    check_agentforge_worker --mode dedicated --json \
    > /var/lib/agentforge/v28/worker-preflight.json
'
```

Check the preflight exit status. If it fails, inspect locally and **do not
bypass or edit the receipt**. Do not upload the private raw receipt publicly;
the V2.8 output contains only an SHA256 digest of this local input.

## 3. Verify the live host and produce a private evidence receipt

Replace `REVIEWED_40_CHAR_GIT_SHA` with the exact 40-character SHA approved by
an operator who independently checked the repository release:

```bash
cd /opt/agentforge/AgentForge
sudo /opt/agentforge/venv/bin/python \
  scripts/verify_django_v28_host_acceptance.py \
  --expected-commit REVIEWED_40_CHAR_GIT_SHA \
  --preflight-receipt /var/lib/agentforge/v28/worker-preflight.json \
  --output /var/lib/agentforge/v28/host-acceptance.json
```

Return code `0` means **ready for independent operator review only**.
Return code `2` means fail closed. The output file is private `0600`; it will
NEVER overwrite an earlier receipt. For a new attempt, use a different name.
The tool does not activate anything even when all checks pass.

If this is run on GitHub Actions or any host lacking a deployed systemd Worker,
remote DB receipt or trusted root-owned deployment, it MUST return `2`.

## Remaining live and business acceptance blockers

- A human must verify the VM is actually separate from the public web host,
  that its Docker daemon is isolated, and that its deployed checkout/receipt
  comes from the reviewed release. Git SHA comparison is not a signed release
  or remote VM attestation.
- A passing preflight demonstrates only live read-only PostgreSQL checks *at
  the time the preflight was run*. It does not test failover or DB recovery.
- A separate, approved fault drill must prove actual systemd restart
  behavior, stale lease blocking and manual recovery on the same dedicated VM.
- The **three real DeepSeek cases** still require separate user authorization,
  an explicit cost ceiling and credential provisioning. No paid calls occur here.
- Actual Worker timer activation needs a separate, explicit change approval.

**A green CI never overrides these blockers.**
