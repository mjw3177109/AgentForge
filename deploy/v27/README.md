# AgentForge Django V2.7 — source-tree gate before VM staging

**Purpose:** close the V2.5/V2.6 gap where only the root source directory
and Django entrypoint were audited. An attacker with write access to a nested
Python module could evade that shallow metadata check. V2.7 audits nested
files and directories across the Worker source, deployment scripts, Django
example and reviewed systemd templates.

## Execute on a separately managed, trusted dedicated Linux Worker VM

From the reviewed checkout at `/opt/agentforge/AgentForge`:

```bash
python3 scripts/check_django_v23_systemd.py
python3 scripts/check_django_v25_host.py
python3 scripts/check_django_v27_source_tree.py
sudo bash deploy/v24/stage_units.sh --stage-reviewed-units
python3 scripts/audit_django_v24_systemd_host.py --output /tmp/agentforge-v24-audit.json
```

**No script here starts or enables the Worker.** Do not run the stage command
on a public web server or generic shared runner. Inspect all failures before
retrying; these are fail-closed release blockers. The V2.7 source-tree gate
requires root-owned source files/directories with no group/other write access,
readable files, traversable directories, and no symlinks or special files inside
the scanned code trees. It checks these roots:

- `src/`, `scripts/`, `examples/django_host/`, `deploy/` (including staging scripts)
- `pyproject.toml`

The receipt contains fixed failure codes and counts, never source paths,
source bytes, secrets or environment values. It does not read any code
contents, inspect the model API, or connect to Docker or PostgreSQL. It does
not certify the authenticity of the checkout, a Git commit, or a distant VM:
an administrator must independently pin and review the deployed Git commit
and secure the parent directories; file metadata is a point-in-time snapshot.

## Remaining release-blocking live acceptance

1. Obtain an independently provisioned persistent dedicated Linux VM;
   prove host identity to the operator and inspect the installed unit state.
2. Provision separately authorized remote PostgreSQL with certificate
   verification, bounded credentials, migrations and explicit recovery.
3. Inspect Docker daemon isolation and approved immutable image identity.
4. Run the existing 13-item Worker readiness check with a deliberately
   empty queue, preserving any lease fail-closed behavior.
5. Only with a separate explicit budget and approval, run three genuine
   DeepSeek cases. Archive redacted audit evidence; never put keys in CI.

**Status:** no VM provided; no remote PostgreSQL handshake performed; no
paid DeepSeek calls. Passing CI is not a production deployment approval.
