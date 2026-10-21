# AgentForge V4.1 — proof of P2 execution and Java service idempotency

## Status

- **Development stage:** additive V4.1 acceptance patch, built on V4.0 Preview.
- **Offline:** pure-Python negative tests and static workflow checks; these are **not** a real DeepSeek test.
- **Live:** three new paid DeepSeek rounds have **not** been started by this package.
- **Release:** no automatic PR merge, branch widening, production deployment, or permission changes.

## Why V4.1 exists

The V3 P4.1 canary previously recorded that `--v3-safe-repair` was added to the CLI invocation. This is insufficient to prove `SafeRepairRuntime.execute()` actually ran for every task. Separately, the MySQL ledger unique index test does not prove Java `PointsService.earnAfterPayment(...)` credits once under retries and concurrency. Both were unverified.

V4.1 adds two *separate* gates and **does not remove or modify the 10 existing independent V2 gates**:

1. `P2_EXECUTION_TRACE`: a trusted wrapper instruments each real `SafeRepairRuntime.execute()` call in the CLI subprocess. Its task ID, agent, outcome and independent verification commands must correspond one-for-one with the autonomous protocol records. Model-generated text or a CLI flag alone is not accepted as execution evidence.
2. `java_mysql_service_exactly_once`: copies the finished generated server into a disposable directory, injects a **maintainer-owned** JUnit test in that copy only, and runs it against a uniquely named MySQL database on `127.0.0.1:3306`. It calls the Java service twice with one `businessNo` and concurrently on two threads, asserting one ledger entry and one credit to the points balance. Transaction advice is enabled through Spring. A mismatched/incompatible implementation is `FAIL`, never skipped or massaged into PASS.

The trusted JUnit test uses a fixed constructor/interface contract based on the existing synthetic shop fixture. **A different legitimate implementation can be incompatible with the harness**, causing a blocked result. This is not a generic proof of payment webhook handling, network retries, Redis failures, real users, payment settlement, or multi-tenant isolation.

## Trust boundary and artifacts

- The external DeepSeek runner has access to the model key but **no attestation keys**. The *additional* V4.1 service/MySQL subprocesses inherit only a minimal allowlisted environment containing localhost test-database credentials and JVM settings, not the model or GitHub runtime tokens.
- An isolated verifier job checks the original V2 10-gate evidence with the P1 signature key and then verifies the new V4.1 P2 trace/Java log with a **separate V4.1 HMAC key**.
- Attestations bind `github.run_id`, exact `github.sha`, model identifier, P1 manifest hash, and the new 6 evidence files. They cannot authorize a release.
- Generated project files are never modified by injected JUnit tests; only a disposable copy receives the trusted file. The schema is always `agentforge_v41_<run_id>_<round>` and is created using local MySQL 8, with cleanup only if creation succeeded.
- Unknown paths, symlinked evidence, missing tasks, P2 markers without actual calls, invalid Maven results, skipped gates, stale signatures, and summary contradictions fail closed.

## GitHub installation

Branch `feature/v4-1-acceptance` is based on the V4 commit `bb847313c654093d2586696c1d17106db88a68e4`. This patch introduces new V4.1 paths and makes **one test-only correction** in `tests/test_v3_memory.py`: reuse the identical signed envelope for the idempotent re-import test. Re-signing generates different bytes and remains rejected. No V3/V4 runtime code, authorization checks, or production configuration is changed.

For offline tests:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q tests/test_v41_proof.py tests/test_v41_workflows.py
python scripts/v41_scope_audit.py
python -m pytest -q
python protocol_bundle/scripts/validate_protocol.py
```

Expected push-triggered offline workflow: `.github/workflows/agentforge-v41-offline.yml`, Python 3.11 and 3.12, three suite repeats each. CI acceptance must be checked on the **exact V4.1 commit**.

For **paid real-model acceptance**, only a repository maintainer should manually run `.github/workflows/agentforge-v41-live.yml` after reviewing the V4.1 source, the trusted verifier SHA, costs, GitHub variables and secrets. It requires explicit confirmation `RUN_V41_THREE_PAID_DEEPSEEK_ROUNDS`. Credentials required: `AGENTFORGE_LLM_API_KEY`, `AGENTFORGE_LLM_BASE_URL`, `AGENTFORGE_LLM_MODEL`, `AGENTFORGE_V3_EVIDENCE_KEY`, and a separate `AGENTFORGE_V41_ATTEST_KEY`. These secrets must be protected separately. No such workflow is automatically triggered by a push or PR.

The independent output statuses `V41_SYNTHETIC_CANDIDATE` and `V41_SYNTHETIC_INDEPENDENTLY_ATTESTED` remain restricted to **synthetic** benchmarks. Production readiness needs a separate authorized integration suite, operator signoff and deployment controls.

## Acceptance decision

**PASS candidate** only when all 3 distinct DeepSeek rounds have four actual P2 Agent execution traces, Reviewer APPROVE, exactly 10/10 original independent gates plus the new Java service behavior gate, and an independently verified P1+V4.1 attestation bound to the same run/commit/model. Partial results stay FAIL. PRs remain Draft pending explicit human approval.

## Discovered three-cycle regression (2026-10-21)

The first V4.1 Python 3.11 three-cycle CI run failed on its **second** repetition because an older test regenerated a timestamp-bearing HMAC envelope for an already recorded Run ID. The existing memory replay defense properly rejected it. We changed only the test to reuse the original envelope and expanded the offline workflow paths filter to include this security regression test. The security check was not modified and no CI pass is claimed until the new exact SHA completes.
