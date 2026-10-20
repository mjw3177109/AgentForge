# V3.0 P0 minimal patch — only new files

Copy ZIP contents into repository root on a separate experimental branch, e.g. `feature/v3-governance-p0` after V2 stabilizes. Nothing in this ZIP modifies existing repo files. `PLACEMENT.md` is pack-level instructions, not required to copy.

Added:
- `src/agentforge/governance/__init__.py`
- `src/agentforge/governance/preflight.py`
- `scripts/v3_preflight.py`
- `tests/test_v3_preflight.py`
- `examples/v3_preflight_request.json`
- `docs/V30_INCREMENTAL_RFC.md`

Use `python -m pip install -e '.[dev]'` and `pytest -q tests/test_v3_preflight.py` after applying. All checks here are local and read-only; no GitHub push has been performed.
