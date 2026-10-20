# AgentForge V2.0 bounded supervision

**No external VM is created by this repository.**

Production chain: systemd ExecStartPre (12 read-only security checks)
-> process_agentforge_supervised_queue (one pending task)
-> supervise_agentforge_job (bounded process group)
-> run_agentforge_job (candidate-only result).
Use 780s per job, 960s systemd TimeoutStartSec.

```bash
python examples/django_host/manage.py check_agentforge_worker --mode dedicated --json
python examples/django_host/manage.py process_agentforge_supervised_queue --mode dedicated --include-autonomous --timeout-seconds 780 --json
```

An expired heartbeat is NOT evidence that old processes or Docker containers
have stopped. Follow deploy/v19/README.md before manual recovery.
The CI PostgreSQL test exercises real bounded OS supervision of a synthetic
read-only AUDIT job. It does not prove independent VM or paid DeepSeek tests.
