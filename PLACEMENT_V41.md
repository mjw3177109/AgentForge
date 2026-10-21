# V4.1 additive patch installation

**Repository**: `mjw3177109/AgentForge`

**Target branch**: `feature/v4-1-acceptance` (based on `feature/v4-control-plane`, SHA `bb847313c654093d2586696c1d17106db88a68e4`).

The package only adds these paths (no V2/V3/V4 replacement files):

- `src/agentforge/v41/__init__.py`
- `src/agentforge/v41/proof.py`
- `src/agentforge/v41/service_gate.py`
- `src/agentforge/v41/attestation.py`
- `scripts/v41_instrumented_cli.py`
- `scripts/v41_hardened_benchmark.py`
- `scripts/v41_live_acceptance.py`
- `scripts/v41_attest.py`
- `scripts/v41_scope_audit.py`
- `benchmarks/v41_trusted/TrustedPointsExactlyOnceTest.java`
- `.github/workflows/agentforge-v41-offline.yml`
- `.github/workflows/agentforge-v41-live.yml`
- `tests/test_v41_proof.py`
- `tests/test_v41_workflows.py`
- `docs/V41_REAL_ACCEPTANCE.md`
- `PLACEMENT_V41.md`

Run `python -m pytest -q tests/test_v41_*.py` in the checkout after installation. A failure to run Maven/MySQL locally must be reported as unavailable; the paid live workflow remains manual-only. See `docs/V41_REAL_ACCEPTANCE.md` for controls and limits.
