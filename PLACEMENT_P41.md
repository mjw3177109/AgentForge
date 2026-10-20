# P4.1 incremental patch placement

**GitHub repository:** `mjw3177109/AgentForge`
**Isolated V3 branch:** `feature/v3-p41-integration` (created at `fbb4eabab1b42b26ee1f545c38729dadc68541c5`).
**PR #22:** keep unchanged and Draft.

This ZIP contains only new P4.1 files; it does not duplicate P0-P4 content.

| New path inside repo | Purpose |
|---|---|
| `src/agentforge/acceptance_p41.py` | V3 P2 opt-in and ten-gate review |
| `scripts/v3_p41_hardened_benchmark.py` | Instrument actual DeepSeek CLI call |
| `scripts/v3_p41_live_acceptance.py` | Three live rounds using immutable V2 gates |
| `scripts/v3_p41_verify.py` | Cross-check P1 signed evidence plus P2 canary |
| `scripts/v3_p41_audit.py` | Baseline ancestry, scope and exact integration diff audit |
| `scripts/v3_p41_install.py` | SHA-pinned additive installer of previously delivered P0-P4 ZIPs |
| `tests/test_v3_p41.py` | Positive and negative regression tests |
| `.github/workflows/agentforge-v30-p41-real-integration.yml` | Manual-only paid live acceptance |
| `docs/V30_P41_REAL_INTEGRATION.md` | Engineering, execution and release constraints |

**Required source packages:** previously provided P0/P1/P2/P3/P4 ZIPs, unchanged. P4.1 installer refuses different hashes, forbidden branches and unexpected overwrites. Default is DRY-RUN.

**Recommended sequence:** P4.1 unzip on V3 branch → `python scripts/v3_p41_install.py --repo-root . --packages-dir PATH_TO_5_ZIPS` → same command with `--apply` → `pip install -e ".[dev]"` → `pytest -q` → protocol verification → inspect git diff → manually commit/push branch → manual workflow dispatch once reviewed.

**Status at artifact creation:** new P4.1 code locally tested; actual full GitHub CI and real paid DeepSeek 3/3 NOT YET RUN. Do not call this release-ready.
