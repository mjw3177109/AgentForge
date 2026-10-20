# AgentForge V3.0 — Incremental Governance RFC (Phase 0)

> Status: PROPOSAL / ISOLATED PROTOTYPE. Not integrated, not deployed, not V2.0 acceptance evidence.

## Goal

Add governance and durable evidence to the existing V2 engine without altering its authority boundaries or replacing its pipeline.

**Non-negotiable:** no permission expansion, no automatic merging, no production deployment, no reviewer self-approval, no skipping verification, no retroactive rewriting of evidence.

## Baseline (checked 2026-10-19)

Repo `mjw3177109/AgentForge`, branch `verify/v2.0-stability`, HEAD `fbb4eabab1b42b26ee1f545c38729dadc68541c5`.
- Standard CI #39103690266 SUCCESS.
- Live DeepSeek #39103687560 FAIL (2/3); 3/3 gate not satisfied.
- PR #22 open, Draft. V3 MUST NOT be merged into the V2 acceptance branch while V2 is unresolved.

## Existing interfaces to reuse

- `src/agentforge/policy.py`: `PolicyEngine`, path handling.
- `src/agentforge/execution_profiles.py`: trusted profile parsing and verification executable allowlist.
- `src/agentforge/autonomous.py`: existing orchestrator, review/repair loop.
- `src/agentforge/evidence.py`: evidence index.
- `src/agentforge/state_machine.py`: task lifecycle.

## V3 milestones

### P0: read-only governance preflight (this patch)

Inputs: repository root, trusted V2 execution profiles, agent identifier, task-proposed file list. The task JSON CANNOT specify permissions or override policy. Verify canonical relative paths, symlink prefixes and the existing write + deny policy. Classify sensitive changes as advisory high-risk. Output JSON only to stdout.

Outcome is `BLOCKED`, `MANUAL_REVIEW_REQUIRED`, or `SCOPE_PRECHECK_OK`. All outcomes include `verification=NOT_EXECUTED` and must not be interpreted as a pass, Reviewer APPROVE, or release decision. Exit 2 for blocked/review-required and 0 for scope precheck only. No shell execution or Git mutation.

This prototype does NOT guarantee dynamic TOCTOU safety and must never replace the workspace runtime's own safety checks.

### P1: immutable evidence envelopes

Design a `run_id/task_id/commit_sha/profile_digest/model_id/timestamp/gate_id/validator_version/result/artifact_digest` envelope. Hash immutable raw test outputs; keep each gate independent and report missing evidence as `UNVERIFIED`. Store separate facts vs LLM opinions. Test tampering, missing signatures, incomplete gates, mixed commits, duplicates, and stale artifacts.

### P2: failure taxonomy and repair guard

Classes: `AUTHORIZATION_DENIED`, `VERIFICATION_SCOPE_GAP`, `COMPILATION_FAILURE`, `TEST_FAILURE`, `BEHAVIORAL_FAILURE`, `EXTERNAL_PROVIDER_ERROR`, `ENVIRONMENT_FAILURE`, `UNKNOWN`. Bound repair attempts; never turn AUTHORIZATION_DENIED or critical unverified behavior into an automatic approval. For Java code edits re-run compilation immediately after each repair.

### P3: task memory (human-reviewed)

Store reproducible signatures, diagnostic evidence and approved mitigations; no long-term memory from unverifiable model assertions. Deduplicate by signature and validator. Memory recommendations can modify plans/prompts only within the original policy envelope.

### P4: adapters (Django / Spring Boot / Vue / React)

Start with detection + read-only verifier manifests; execute only through trusted independent harnesses. Do not write to application trees from the adapter. Do not infer tests from generated code as sole acceptance proof.

## P0 acceptance checklist

1. Existing V2 source and workflow files untouched.
2. Trusted execution profile is the only authorization source.
3. Proposed task cannot enlarge write_scope or remove deny_scope.
4. Traversal, absolute paths, noncanonical paths, and symlink hops blocked.
5. At least one unauthorized proposed file blocks entire manifest.
6. High-risk changes require human review even if inside write scope.
7. Outputs never claim tested/verified/safe-to-merge.
8. No agent, runner, git push, PR or deployment side effects.
9. New tests pass, followed by full original repo tests and protocol validation after local application.

## Installing this optional patch

Overlay ZIP contents at repository root in a *new experimental branch* after V2 stabilization. This patch only adds files. The supplied `examples/v3_preflight_request.json` is a proposed path declaration, not a real benchmark result.

```bash
python -m pip install -e '.[dev]'
pytest -q tests/test_v3_preflight.py
python scripts/v3_preflight.py --repo-root . \
  --profiles benchmarks/v18_hardened/execution-profiles.yaml \
  --agent backend --task examples/v3_preflight_request.json
```

The prototype command prints `SCOPE_PRECHECK_OK`, not `PASS`, for an authorized non-high-risk path; it does not require DeepSeek credentials. On integration, prohibit the task itself from naming the trusted profile path, ensure policy source is revision-pinned, and add a race-safe recheck immediately before every filesystem write.

## Development order

Do not link P0 to existing `autonomous-live` without a separate review. First complete V2.0 3/3; then open isolated V3 PR; run offline CI and targeted policy fuzz tests; only after independent audit consider promoting governance checks into the runtime. Maintain a human-only final release gate.
