# V2.3 — Worker restart interlock and systemd contract

This repository DOES NOT provision a persistent VM. No model API is called
by these checks.

## Pre-enable verification on a dedicated Worker

```bash
python scripts/check_django_v23_systemd.py
python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json
python examples/django_host/manage.py inspect_agentforge_leases --json
python examples/django_host/manage.py inspect_agentforge_containers --json --fail-if-any
```

Require **13/13** startup checks. The extra check denies ANY residual lease,
including a lease with an overdue heartbeat or finished job status.
It cannot establish that the old process exited merely by checking the DB.

If a lease remains after a service crash, DO NOT restart the timer. Stop
timer+service, verify all original OS processes and Docker containers have
been accounted for (see deploy/v19/README.md), then explicitly recover the
specific job using the existing trusted operator command. Repeat preflight.

The static systemd contract validator checks the checked-in files only.
Before enabling in a real VM, separately review `systemctl cat
agentforge-worker.service`, `systemctl cat agentforge-worker.timer`,
drop-in overrides, actual service user/permissions, database TLS,
cgroup behavior and logs. Do not enable timer before an operator approves.

CI includes a real ephemeral PostgreSQL abandoned-lease/recovery drill.
This DOES NOT demonstrate VM reboot, persistent host isolation,
live provider identity, or production incident recovery.
