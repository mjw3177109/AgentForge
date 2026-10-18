# AgentForge V2.0 — Stability acceptance (no production release)

## Purpose and baseline

Baseline: V1.9 real DeepSeek hardened Run #29 passed with Reviewer APPROVE. One successful run is not a stability claim.

V2.0 must verify reliability and fail closed. The validation branch is `verify/v2.0-stability`; this does not push generated storefront code to production, merge main, or create a release. It exercises only an isolated disposable benchmark repository and GitHub Actions MySQL/Redis service containers.

## Release gate (strict)

1. Python 3.11 and 3.12 each execute full pytest and protocol validation **three independent times**.
2. Fault injection passes for HTTP 429, 500, 502, and 503; a temporary failure must recover, repeated failures must raise `LLMError` and never produce false success.
3. A **fresh real-model** DeepSeek hardened autonomous benchmark is executed **three times**, with an independently created benchmark repository each round.
4. Every round requires: final `SUCCESS`, four distinct initial Agent successes (Database, Backend, Miniapp, Admin), a non-empty commit on every task run, maximum two reviewer Repairs per task, final Reviewer `APPROVE`, and **no auto PR/push**.
5. After **every** real round, independently rerun immutable Database, Backend, Miniapp and Admin Node contract tests, Maven tests, Vue/Vite npm build, and apply the generated SQL migration to an **isolated ephemeral MySQL schema**. Do not turn skipped tests into PASS.
6. `artifacts/v20-stability/summary.json` must read `overall=PASS`, `rounds_required=3`, `rounds_passed=3`; archive all per-round generated repositories, logs, failures, and independent gate results.
7. If an HTTP fault, Reviewer rejection, contract mismatch, Maven/Vite/MySQL failure, or timeout occurs, mark the affected round FAIL; finish later rounds for evidence but return nonzero overall.

## Workflow

GitHub Actions: `.github/workflows/agentforge-v20-stability.yml`. Push to `verify/v2.0-stability` triggers offline repetition followed by three sequential paid model rounds. Alternatively dispatch the workflow manually. Must have repository variable `AGENTFORGE_LLM_BASE_URL`, variable `AGENTFORGE_LLM_MODEL`, and secret `AGENTFORGE_LLM_API_KEY`. Missing credentials **fail** the live job, rather than silently skipping.

Offline command:

```bash
python -m pip install -e ".[dev]"
for iteration in 1 2 3; do
  pytest -q
  python protocol_bundle/scripts/validate_protocol.py
done
```

Live command in an ephemeral GitHub runner with isolated MySQL and Redis services:

```bash
python scripts/run_v20_stability.py --rounds 3 --round-timeout 1200 --output-dir artifacts/v20-stability
```

## Scope limits

- The benchmark is a **hardened synthetic storefront fixture**. Its successful completion does not establish payment provider webhook integration, real user sessions, real multi-tenant authorization, production traffic performance, service-level uptime, or safe release readiness.
- The three fresh DeepSeek runs measure acceptance reliability on **this one task and model configuration**, not general task distribution performance. The observed pass rate should be reported literally (e.g. 2/3), never portrayed as a population reliability guarantee.
- The workflow deliberately excludes production database access and any automatic merging.
- Artifacts are retained for seven days by the workflow. Record final run links and outcome when complete.
