# Concurrent AgentForge IDs

Legacy numeric IDs such as `REQ-000201` remain valid.

New concurrently-created work should prefer distributed human-readable IDs:

```text
REQ-261017080100-A1B2
ADR-261017080100-A1B2
TASK-261017080100-A1B2-01
```

The middle component is UTC `YYMMDDHHMMSS`; the final four hex characters are generated independently by Core. This avoids relying on a shared local counter when multiple developers/agents plan from the same GitHub baseline.
