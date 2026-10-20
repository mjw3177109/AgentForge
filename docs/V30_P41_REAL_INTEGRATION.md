# AgentForge V3.0 P4.1 — Real integrated acceptance

**Status:** implementation and offline module regression ready; full remote GitHub CI and paid real-model acceptance are **NOT YET RUN**. This is NOT a production readiness certificate.

## Background and the P4 gap

V2.0 commit `fbb4eabab1b42b26ee1f545c38729dadc68541c5` remains the reviewed baseline. The known real-model Run #39103687560 is **FAIL 2/3**; standard CI #39103690266 is SUCCESS. Earlier failure Run #39092253716 and successful Run #39092231063 are historical; no duplicate notifications. Draft PR #22 must remain unmodified.

P4 had a critical coverage gap: its real three-round job called the V2 benchmark without `--v3-safe-repair`. A V2 PASS cannot be promoted to V3 P2 automatic-repair verification. **P4.1 closes this gap** with a separate canary invoking the *same hardened fixture and immutable gates*, but instrumenting the CLI call to include `--v3-safe-repair`.

## New pieces

1. `scripts/v3_p41_hardened_benchmark.py`: tight wrapper around the existing V18 hardened benchmark: append `--v3-safe-repair` ONLY to the trusted `agentforge autonomous-live` invocation. Emits the P2 opt-in marker once. Fails if the integrated `AutonomousDevelopmentPipeline` lacks the P2 opt-in constructor field.
2. `scripts/v3_p41_live_acceptance.py`: three genuinely new DeepSeek rounds, each on a disposable benchmark worktree, with V2's unchanged post-run Node/Maven/Vite/MySQL schema/concurrency 10-gate verifier. Requires marker, four initial Agent successes, final Reviewer APPROVE, three rounds, verified bound for repairs, and all 10 gates per successful round. Prints FAIL and returns nonzero on any gap.
3. `src/agentforge/acceptance_p41.py`: strict static consistency check for `3/3`, canary mode and gate coverage; **unsigned result alone is NOT trusted evidence**.
4. `scripts/v3_p41_verify.py`: after P1 HMAC verification of all source snapshots/logs, run an additional independent P4.1 canary-mode check; refuses legacy V2 3/3 evidence with no P2 marker. A positive result is a **synthetic V3 P2 canary acceptance**, not full business production readiness.
5. `scripts/v3_p41_audit.py`: read-only safety audit on a `feature/v3-*` or `experiment/v3-*` branch. Requires reviewed V2 SHA ancestry, clean tracked code, unchanged V2 policy/workspace/verification code and hardened contracts; verifies P2 modified ONLY `autonomous.py` and `cli.py` and that modifications equal the pinned P2 installer’s expected diff; checks Backend `server/src/main/**` write ceiling.
6. `scripts/v3_p41_install.py`: optional local installer for **the exact SHA256-pinned original P0–P4 ZIPs**, with default dry-run. It validates archive hashes, paths, collisions and branch lineage before writing; applies only additive files and the two precise opt-in modifications, without commits/push/production actions.
7. `.github/workflows/agentforge-v30-p41-real-integration.yml`: manual-only orchestration, Python 3.11/3.12 three full pytest+protocol passes, read-only scope audit, paid real-model 3-round canary, independently keyed HMAC signing and cross-check on a separately pinned reviewed commit. Workflow `permissions: contents: read`; only the live job has DeepSeek API credentials, only the attestation job has signing key.
8. `tests/test_v3_p41.py`: new negative and positive regressions, including cryptographically signed legacy V2 PASS rejected for missing V3 opt-in, tampered log rejected, missing 10th gate rejected, and exact-diff integration checks.

## Three different evidence levels — never conflate

| Level | What it supports | Does NOT establish |
|---|---|---|
| Offline module regression | Local P0–P4+P4.1 invariants and safe installer behavior | Python 3.11/3.12 real-repo CI, DeepSeek reliability |
| Remote full GitHub CI | Clean checkout + complete pytest+protocol 3x for both 3.11/3.12 | External-model ability or business idempotency |
| Signed real P4.1 canary 3/3 | Trusted P2 CLI opt-in during real external-model runs; 10 post-run fixture gates each | A reviewer necessarily required a repair; Java exactly-once service correctness; real production loads |

**The actual repair recovery path** additionally needs a deliberately injected failure that forces P2 to diagnose and retry. Existing `tests/test_v3_repair.py` exercises this with fault injection and rollback under fixture conditions; running three real DeepSeek rounds may not trigger a reviewer repair. Track `repair_agents` separately; `repair_agents=[]` is a valid success of execution mode but NOT evidence of real reviewer-driven recovery.

## Safe integration into an independent V3 branch

The designated branch is `feature/v3-p41-integration`, anchored at the V2 SHA above. Do not change Draft PR #22 or the base branch. Place P0–P4 ZIPs alongside the extracted P4.1 installation directory, then execute:

```bash
# First unzip P4.1 ZIP in the V3 working copy, then:
python scripts/v3_p41_install.py --repo-root . --packages-dir /path/to/previous/zips
python scripts/v3_p41_install.py --repo-root . --packages-dir /path/to/previous/zips --apply
python -m pip install -e ".[dev]"
python -m pytest -q
python protocol_bundle/scripts/validate_protocol.py
# Review changed files, then commit/push to feature/v3-p41-integration using normal Git tooling.
```

Once committed, the remote GitHub Actions job is **manual-only**. In Actions select `AgentForge V3 P4.1 Real Integration (Manual)` on the new branch, provide confirmation exactly `RUN_THREE_PAID_DEEPSEEK_ROUNDS` and a reviewed `trusted_verifier_sha` (40 lowercase hexadecimal). The real live job requires `AGENTFORGE_LLM_BASE_URL`, `AGENTFORGE_LLM_MODEL`, `AGENTFORGE_LLM_API_KEY` and distinct `AGENTFORGE_V3_EVIDENCE_KEY`. Do not print secrets or weaken permissions to unblock the run.

## Explicit non-goals

- No automatic merging, auto-publishing, production DB access or external deployment.
- No new Agent write access for `server/src/test/**`, tests/fixtures, `.github/**`, or other denied paths.
- No claim that MySQL ledger uniqueness proves Java service-layer exactly-once crediting.
- No automatic authorization increase based on past memory; P3 remains advisory only.
- No paid DeepSeek calls during the offline tests or at branch creation.

## Exit criteria for P4.1

- [ ] Full remote Python 3.11 CI: 3x full suite + protocol PASS
- [ ] Full remote Python 3.12 CI: 3x full suite + protocol PASS
- [ ] Scope audit PASS and exact P2 opt-in diff confirmed
- [ ] 3 new real DeepSeek rounds: four Agents SUCCESS, Reviewer APPROVE, bounded repair
- [ ] Each real successful round: **10/10 independent gates PASS** including MySQL concurrent business_no uniqueness
- [ ] Trusted independent signer on separately reviewed SHA returns `P41_V3_P2_ATTESTED_PASS`
- [ ] Report repair_agents and separately test service-layer idempotency before any release claim
- [ ] Human review all evidence; PR and production remain untouched
