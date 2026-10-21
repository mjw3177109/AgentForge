# AgentForge V2.5 — host prerequisite and safe staged-unit handoff

**No VM is provisioned by this code. No paid model calls.** Deploy this only
on a reviewed, separately operated Linux Worker VM, not on the public web
server or a general developer workstation.

## Read-only host gate

```bash
python3 scripts/check_django_v25_host.py
```

Expected: 5/5. The checks include the non-root agentforge Unix account,
root-owned and non-group/world-writable source tree and managing executable,
trusted root-controlled virtualenv/bin and executable, and the secret
environment file owned by root with exactly mode 0600, no symlinks or extra
hard links. The script uses only filesystem metadata and pwd lookup.
**It does not read secret contents.**

Existing runbook prerequisites remain: verified remote TLS PostgreSQL,
dedicated Docker daemon, approved image ID, trusted Django settings,
13/13 Worker preflight, plus operator inspection of actual systemd status.

## Stage units after explicit review

```bash
python3 scripts/check_django_v23_systemd.py
python3 scripts/check_django_v25_host.py
sudo bash deploy/v24/stage_units.sh --stage-reviewed-units
python3 scripts/audit_django_v24_systemd_host.py
```

Stage script acquires an exclusive OS flock. It will not overwrite installed
units or drop-ins; it rejects an active/enabled worker timer. On failure it
attempts to roll back ONLY the fresh units it created when their bytes still
match the approved templates, then reloads systemd. Unexpected modifications
or ownership anomalies require explicit operator inspection rather than
force-deletion. It never starts, enables, or restarts a worker, never runs
migrations, and never calls DeepSeek.

This is a local host metadata audit only, not cryptographic attestations of
all source files or an actual production VM deployment. CI tests use fixture
files and never operate on /etc/systemd/system.
